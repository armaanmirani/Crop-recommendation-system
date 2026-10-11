"""Synthetic fixtures test integration behavior, not live portal availability."""
from datetime import timedelta
import io
import json
import socket
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
import pytest
import app as application
import market

FILTERS = {"crop": "rice", "state": "Maharashtra"}
SOIL = {"N":90, "P":42, "K":43, "temperature":20.9, "humidity":82, "ph":6.5, "rainfall":203}


def record(**overrides):
    return {"state":"Maharashtra", "district":"Pune", "market":"Pune", "commodity":"Paddy(Dhan)(Common)",
            "variety":"Common", "grade":"FAQ", "arrival_date":market.today().strftime("%d/%m/%Y"),
            "min_price":"2300", "max_price":"2600", "modal_price":"2450", **overrides}


@pytest.fixture
def client():
    application.app.config['TESTING'] = True
    with market.QUOTE_LOCK:
        market.QUOTES.clear()
    return application.app.test_client()


def csv_bytes(rows):
    out = io.StringIO()
    import csv
    writer = csv.DictWriter(out, fieldnames=record().keys())
    writer.writeheader(); writer.writerows(rows)
    return out.getvalue().encode()


def upload(client, rows, **overrides):
    return client.post('/api/market-import',data={**FILTERS,'confirmed_unit':'INR/quintal','portal':'agmarknet',
        'file':(io.BytesIO(csv_bytes(rows)),'prices.csv'), **overrides},content_type='multipart/form-data')


def test_status_never_exposes_key(client, monkeypatch):
    monkeypatch.setenv('DATA_GOV_API_KEY','test-only-secret')
    response=client.get('/api/market-status')
    assert response.json['api_key_configured']
    assert 'test-only-secret' not in response.get_data(as_text=True)
    assert response.json['commodities']['rice'][0]=='Paddy(Dhan)(Common)'


def test_missing_key_is_actionable_not_fake_prices(client, monkeypatch):
    monkeypatch.delenv('DATA_GOV_API_KEY',raising=False)
    response=client.get('/api/market-prices',query_string=FILTERS)
    assert response.status_code==503
    assert 'API key' in response.json['error']
    assert 'records' not in response.json


@pytest.mark.parametrize('patch',[{'state':''},{'crop':'wheat'},{'commodity':'Banana'},
    {'date':'01/01/2026'},{'date':(market.today()+timedelta(days=1)).isoformat()},
    {'offset':'bad'},{'offset':'-1'},{'offset':'10001'},{'state':'x'*101}])
def test_bad_lookup_filters(client,patch):
    assert client.get('/api/market-prices',query_string={**FILTERS,**patch}).status_code==400


def test_csv_conversion_location_and_date(client):
    response=upload(client,[record(),record(state='Punjab'),record(commodity='Rice')])
    assert response.status_code==200
    assert len(response.json['records'])==1
    quote=response.json['records'][0]
    assert quote['modal_price']==2450 and quote['price_per_kg']==24.5
    assert quote['original_unit']=='INR/quintal'
    assert quote['report_date']==market.today().isoformat()
    assert quote['source']=='Agmarknet portal CSV (user-supplied)'
    assert not quote['stale'] and quote['quote_id']


@pytest.mark.parametrize('patch',[{'modal_price':'nan'},{'modal_price':'-20'},
    {'modal_price':'99999'},{'arrival_date':'bad'},
    {'arrival_date':(market.today()+timedelta(days=1)).strftime('%d/%m/%Y')},{'district':''}])
def test_invalid_records_are_not_usable(client,patch):
    response=upload(client,[record(**patch)])
    assert response.status_code==200
    assert response.json['records']==[]
    assert any('Skipped 1' in warning for warning in response.json['warnings'])


def test_mixed_units_are_not_silently_converted():
    with pytest.raises(ValueError,match='Unsupported price unit'):
        market.parse_record({**record(),'unit':'INR/kg'},market.filters(FILTERS),'test')


def test_coconut_cannot_be_converted_from_count_to_weight(client):
    response=upload(client,[record(commodity='Coconut')],crop='coconut')
    assert response.json['records']==[]
    assert any('per nut' in warning for warning in response.json['warnings'])


def test_stale_price_is_shown_but_cannot_be_applied(client):
    old=(market.today()-timedelta(days=8)).strftime('%d/%m/%Y')
    quote=upload(client,[record(arrival_date=old)]).json['records'][0]
    assert quote['stale']
    with pytest.raises(ValueError,match='over 7 days'):
        market.resolve_quote(quote['quote_id'],'rice')


def test_quote_price_and_provenance_survive_recommendation(client):
    quote=upload(client,[record()]).json['records'][0]
    response=client.post('/api/recommend',json={**SOIL,'market':{'rice':{
        'quote_id':quote['quote_id'],'price_per_kg':9999,'yield_kg_per_hectare':4000,'cost_per_hectare':50000}}})
    assert response.status_code==200
    economics=response.json['recommendations'][0]['market']
    assert economics['price_per_kg']==24.5  # Untrusted browser price cannot overwrite a selected quote.
    assert economics['estimated_profit']==48000
    assert economics['price_source']['market']=='Pune'
    assert economics['price_source']['report_date']==market.today().isoformat()


def test_mismatched_and_expired_quote_rejected(client,monkeypatch):
    quote=upload(client,[record()]).json['records'][0]
    with pytest.raises(ValueError,match='does not belong'):
        market.resolve_quote(quote['quote_id'],'maize')
    now=market.time.monotonic()
    monkeypatch.setattr(market.time,'monotonic',lambda: now+3601)
    with pytest.raises(ValueError,match='expired'):
        market.resolve_quote(quote['quote_id'],'rice')


def test_upload_unit_and_schema_validation(client):
    assert upload(client,[record()],confirmed_unit='').status_code==400
    assert upload(client,[record()],portal='other').status_code==400
    response=client.post('/api/market-import',data={**FILTERS,'confirmed_unit':'INR/quintal',
        'file':(io.BytesIO(b'a,b\n1,2'),'prices.csv')})
    assert response.status_code==400
    assert client.post('/api/market-import').status_code==400


def test_official_api_query_and_pagination(client,monkeypatch):
    monkeypatch.setenv('DATA_GOV_API_KEY','test-api-key')
    captured=[]
    class Opener:
        def open(self,req,timeout):
            captured.append(req.full_url)
            assert timeout==15
            return io.BytesIO(json.dumps({'records':[record()],'total':120}).encode())
    monkeypatch.setattr(market,'build_opener',lambda *args: Opener())
    response=client.get('/api/market-prices',query_string={**FILTERS,'date':market.today().isoformat()})
    assert response.status_code==200
    assert response.json['next_offset']==1
    assert response.json['records'][0]['source']=='Agmarknet via data.gov.in API'
    query=parse_qs(urlparse(captured[0]).query)
    assert query['filters[commodity]']==['Paddy(Dhan)(Common)']
    assert query['filters[state]']==['Maharashtra']
    assert query['filters[arrival_date]']==[market.today().strftime('%d/%m/%Y')]
    assert query['api-key']==['test-api-key']
    assert 'test-api-key' not in response.get_data(as_text=True)


@pytest.mark.parametrize('failure,status',[(HTTPError('secret-url',403,'denied',{},None),503),
    (HTTPError('secret-url',429,'limited',{},None),429),(URLError('test-api-key'),503)])
def test_upstream_errors_are_sanitized(client,monkeypatch,failure,status):
    monkeypatch.setenv('DATA_GOV_API_KEY','test-api-key')
    class Opener:
        def open(self,*args,**kwargs):
            raise failure
    monkeypatch.setattr(market,'build_opener',lambda *args: Opener())
    response=client.get('/api/market-prices',query_string=FILTERS)
    assert response.status_code==status
    assert 'test-api-key' not in response.get_data(as_text=True)
    assert 'secret-url' not in response.get_data(as_text=True)


@pytest.mark.parametrize('payload',[b'not-json',b'[]',b'{"error":"invalid API key"}'])
def test_bad_upstream_response(client,monkeypatch,payload):
    monkeypatch.setenv('DATA_GOV_API_KEY','test-api-key')
    class Opener:
        def open(self,*args,**kwargs):
            return io.BytesIO(payload)
    monkeypatch.setattr(market,'build_opener',lambda *args: Opener())
    assert client.get('/api/market-prices',query_string=FILTERS).status_code==502


def test_csv_date_filter_and_deduplication(client):
    yesterday=(market.today()-timedelta(days=1)).strftime('%d/%m/%Y')
    response=upload(client,[record(),record(),record(arrival_date=yesterday)],date=market.today().isoformat())
    assert len(response.json['records'])==1


def test_agmarknet_portal_column_names_and_state_specific_export(client):
    contents=('District Name,Market Name,Commodity,Variety,Grade,Min Price (Rs./Quintal),Max Price (Rs./Quintal),Modal Price (Rs./Quintal),Price Date\n'
        f'Pune,Pune,Paddy(Dhan)(Common),Common,FAQ,2300,2600,2450,{market.today().strftime("%d %b %Y")}\n').encode()
    response=client.post('/api/market-import',data={**FILTERS,'confirmed_unit':'INR/quintal',
        'file':(io.BytesIO(contents),'export.csv')})
    assert response.status_code==200
    quote=response.json['records'][0]
    assert quote['price_per_kg']==24.5
    assert quote['state']=='Maharashtra' and quote['state_from_export_filter']
    assert any('CSV omits State' in warning for warning in response.json['warnings'])


@pytest.mark.parametrize('reason,code',[(TimeoutError(),'UPSTREAM_TIMEOUT'),
    (socket.gaierror(),'DNS_ERROR'),(ssl.SSLCertVerificationError(),'TLS_CERTIFICATE_ERROR'),
    (ssl.SSLError(),'TLS_CONNECTION_ERROR'),(ConnectionRefusedError(),'CONNECTION_REFUSED'),
    (ConnectionResetError(),'CONNECTION_RESET'),('test-api-key','NETWORK_ERROR')])
def test_safe_network_diagnostics(client,monkeypatch,caplog,reason,code):
    monkeypatch.setenv('DATA_GOV_API_KEY','test-api-key')
    class Opener:
        def open(self,*args,**kwargs):
            raise URLError(reason)
    monkeypatch.setattr(market,'build_opener',lambda *args: Opener())
    response=client.get('/api/market-prices',query_string=FILTERS)
    assert response.status_code==503 and response.json['error_code']==code
    assert code in caplog.text
    assert 'test-api-key' not in caplog.text + response.get_data(as_text=True)
