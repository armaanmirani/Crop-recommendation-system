const form = document.querySelector('#field-form');
const button = document.querySelector('#submit');
const error = document.querySelector('#form-error');
const names = {random_forest: 'Random Forest', xgboost: 'XGBoost'};
let latestReport = null;
let metadataReady = false;
let commodityMap = {};
let priceFilters = null;
let nextOffset = null;
const selectedQuotes = {};
const money = value => new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR', maximumFractionDigits:2}).format(value);
const percent = value => `${(value * 100).toFixed(1)}%`;
const node = (tag, className, text) => {const element = document.createElement(tag); if(className) element.className = className; if(text !== undefined) element.textContent = text; return element;};

async function getMetadata() {
  try {
    const response = await fetch('/api/metadata');
    if (!response.ok) throw new Error('Models are unavailable. Train the models, then restart the app.');
    const metadata = await response.json();
    document.querySelector('#model').value = metadata.selected_model;
    const tbody = document.querySelector('#market-rows');
    metadata.crops.forEach(crop => {
      const row = node('tr'); row.dataset.crop = crop;
      row.append(node('td', '', crop));
      ['price_per_kg','yield_kg_per_hectare','cost_per_hectare'].forEach((field, index) => {
        const cell = node('td'); const input = node('input');
        input.type = 'number'; input.min = '0'; input.step = 'any'; input.max = String(index === 2 ? 1000000000 : 1000000);
        input.dataset.field = field; input.setAttribute('aria-label', `${crop} ${['price in rupees per kg','yield in kg per hectare','cost in rupees per hectare'][index]}`);
        input.placeholder = '—'; cell.append(input); row.append(cell);
        if(field === 'price_per_kg') input.addEventListener('input', () => {delete selectedQuotes[crop]; renderSelectedQuotes();});
      });
      tbody.append(row);
    });
    const grid = document.querySelector('#model-metrics'); grid.replaceChildren();
    Object.entries(metadata.metrics).forEach(([name, metrics]) => {
      const card = node('div', 'metric-card');
      card.append(node('h3','',names[name]),node('span','metric-value',percent(metrics.accuracy)),node('p','','Held-out test accuracy'),node('p','',`Macro-F1: ${metrics.macro_f1.toFixed(3)}`));
      grid.append(card);
    });
    grid.append(node('div','metric-caption',`${metadata.samples.toLocaleString()} samples · ${metadata.split.training} training / ${metadata.split.validation} validation / ${metadata.split.test} test. Final models fitted on ${metadata.split.final_training} training + validation samples. Selected: ${names[metadata.selected_model]}. These are dataset results, not field-trial accuracy.`));
    metadataReady = true;
  } catch (failure) {
    document.querySelector('#model-metrics').textContent = failure.message;
    error.textContent = failure.message; error.hidden = false;
  }
}

document.querySelector('#priority').addEventListener('input', event => {document.querySelector('#priority-value').textContent = `${Math.round(event.target.value * 100)}%`;});
document.querySelector('#demo').addEventListener('click', () => {
  form.reset(); document.querySelector('#priority-value').textContent = '0%';
  error.hidden = true; document.querySelector('#results').hidden = true;
  document.querySelector('#empty-state').hidden = false; latestReport = null;
  Object.keys(selectedQuotes).forEach(crop => delete selectedQuotes[crop]); renderSelectedQuotes();
  document.querySelector('#price-results').replaceChildren(); document.querySelector('#price-error').hidden = true;
  document.querySelector('#next-prices').hidden = true; nextOffset = null;
});

form.addEventListener('submit', async event => {
  event.preventDefault(); error.hidden = true;
  if (!metadataReady) {error.textContent = 'Model data is unavailable. Refresh after the models are ready.'; error.hidden = false; return;}
  const values = Object.fromEntries(new FormData(form));
  ['N','P','K','temperature','humidity','ph','rainfall','area_hectares','market_weight'].forEach(key => {values[key] = Number(values[key]);});
  values.market = {};
  for (const row of document.querySelectorAll('#market-rows tr')) {
    const inputs = [...row.querySelectorAll('input')];
    if (inputs.every(input => input.value === '')) continue;
    if (inputs[0].value !== '' && inputs[1].value === '' && inputs[2].value === '') continue;
    if (inputs.some(input => input.value === '')) {
      error.textContent = `Complete price, yield, and cost for ${row.dataset.crop}, or leave all three blank.`; error.hidden = false; return;
    }
    values.market[row.dataset.crop] = Object.fromEntries(inputs.map(input => [input.dataset.field, Number(input.value)]));
    if(selectedQuotes[row.dataset.crop]) values.market[row.dataset.crop].quote_id = selectedQuotes[row.dataset.crop].quote_id;
  }
  button.disabled = true; button.textContent = 'Exploring your field…';
  try {
    const response = await fetch('/api/recommend', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(values)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'Unable to make a recommendation.');
    latestReport = {...data, market_inputs:values.market, selected_price_reports:{...selectedQuotes}}; renderResults(data);
  } catch (failure) {error.textContent = failure.message; error.hidden = false;}
  finally {button.disabled = false; const arrow = node('span','arrow-icon'); arrow.setAttribute('aria-hidden','true'); button.replaceChildren(document.createTextNode('Find my crops '), arrow);}
});

function renderResults(data) {
  const cards = document.querySelector('#crop-cards'); cards.replaceChildren();
  document.querySelector('#result-model').textContent = names[data.model];
  data.recommendations.slice(0, 5).forEach((crop, index) => {
    const card = node('article','crop-card');
    card.append(node('div','rank',index === 0 ? (data.market_ranking_applied ? '01 · LEADING PLANNING OPTION' : '01 · STRONGEST MODEL MATCH') : `0${index + 1} · ANOTHER SUITABLE OPTION`));
    const top = node('div','crop-top'); const score = node('div','score',percent(crop.suitability));
    score.append(node('small','','model support')); top.append(node('h3','crop-name',crop.crop), score); card.append(top);
    const track = node('div','score-track'); const fill = node('span'); fill.style.width = percent(crop.suitability); track.append(fill); card.append(track);
    const tags = node('div','crop-meta'); tags.append(node('span','',`${crop.water_need} water demand · demo guide`));
    if(crop.water_caution) tags.append(node('span','','Check irrigation supply'));
    card.append(tags,node('p','rotation',crop.rotation_note));
    if(crop.market) {
      const profit = node('div','profit','Estimated profit for your farm');
      profit.append(node('strong','',money(crop.market.estimated_profit)),node('span','',`${money(crop.market.price_per_kg)}/kg × ${crop.market.yield_kg_per_hectare.toLocaleString()} kg/ha − ${money(crop.market.cost_per_hectare)}/ha; ${data.area_hectares} ha. Your assumptions; excludes unentered expenses.`)); card.append(profit);
      const source = crop.market.price_source;
      if(source && source.report_date) profit.append(node('p','quote-attribution',`${source.source} · ${source.market}, ${source.district}, ${source.state} · ${source.commodity} / ${source.variety} · reported ${source.report_date}. Modal ${money(source.modal_price)}/quintal ÷ 100. Yield and costs are your estimates.`));
      else profit.append(node('p','quote-attribution','Price: manual estimate.'));
    }
    cards.append(card);
  });
  const warnings = document.querySelector('#warnings'); warnings.replaceChildren(...data.warnings.map(text => node('div','warning',text)));
  const comparison = document.querySelector('#comparison'); comparison.replaceChildren();
  Object.entries(data.comparison).forEach(([name,result]) => {
    const card = node('div','comparison-model'); card.append(node('span','',names[name]),node('strong','',result.crop),node('small','',`${percent(result.suitability)} model support`)); comparison.append(card);
  });
  document.querySelector('#empty-state').hidden = true; document.querySelector('#results').hidden = false;
  if(data.recommendations.length && commodityMap[data.recommendations[0].crop]) {document.querySelector('#price-crop').value = data.recommendations[0].crop; updateCommodity();}
  if(window.innerWidth < 800) document.querySelector('#results').scrollIntoView({behavior:'smooth',block:'start'});
}

document.querySelector('#download').addEventListener('click', () => {
  if (!latestReport) return;
  const blob = new Blob([JSON.stringify({...latestReport, note:'Hackathon prototype. Model support is not a calibrated success probability. Financial results use user estimates; confirm with local agricultural guidance.'}, null, 2)], {type:'application/json'});
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = 'terra-field-report.json'; document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
});

function updateCommodity() {
  const crop = document.querySelector('#price-crop').value;
  const select = document.querySelector('#price-commodity'); select.replaceChildren();
  (commodityMap[crop] || []).forEach(name => {const option = node('option','',name); option.value = name; select.append(option);});
}

async function getMarketStatus() {
  const status = document.querySelector('#market-status');
  try {
    const response = await fetch('/api/market-status');
    if(!response.ok) throw new Error('Market price service is unavailable.');
    const data = await response.json(); commodityMap = data.commodities;
    const crops = document.querySelector('#price-crop');
    Object.keys(commodityMap).sort().forEach(crop => {const option = node('option','',crop); option.value = crop; crops.append(option);});
    crops.value = 'rice'; updateCommodity();
    status.textContent = data.api_key_configured ? 'Live API credential configured. Look up reports to check source availability.' : 'Live lookup needs a server API key. Official CSV import and manual estimates are available.';
    const parts = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
    const values = Object.fromEntries(parts.map(part => [part.type,part.value]));
    document.querySelector('#price-date').max = `${values.year}-${values.month}-${values.day}`;
  } catch(failure) {status.textContent = failure.message;}
}

function lookupFilters() {
  return {crop:document.querySelector('#price-crop').value, commodity:document.querySelector('#price-commodity').value,
    state:document.querySelector('#price-state').value.trim(), district:document.querySelector('#price-district').value.trim(),
    market:document.querySelector('#price-market').value.trim(), date:document.querySelector('#price-date').value};
}

function renderSelectedQuotes() {
  const holder = document.querySelector('#selected-quotes'); holder.replaceChildren();
  Object.entries(selectedQuotes).forEach(([crop, quote]) => holder.append(node('p','quote-attribution',`${crop}: ${money(quote.price_per_kg)}/kg · ${quote.commodity}, ${quote.variety} · ${quote.market}, ${quote.state} · ${quote.report_date} · ${quote.source}. Editing the price changes its source to a manual estimate.`)));
}

function renderPriceReports(data) {
  const holder = document.querySelector('#price-results'); holder.replaceChildren();
  data.warnings.forEach(warning => holder.append(node('p','warning',warning)));
  if(data.records.length) holder.append(node('p','input-note',`${data.records.length} usable reports on this page. Ordered by report date within the returned page; choose a relevant variety.`));
  const list = node('div','price-report-list');
  data.records.forEach(quote => {
    const card = node('article','price-report');
    card.append(node('h4','',`${quote.market} · ${quote.district}, ${quote.state}`),
      node('p','',`${quote.commodity} · ${quote.variety} · ${quote.grade}`),
      node('p','',`Reported ${quote.report_date} (${quote.age_days} days old) · ${quote.source}`),
      node('strong','',`Modal ${money(quote.modal_price)}/quintal = ${money(quote.price_per_kg)}/kg`),
      node('p','',`Min ${money(quote.min_price)} / max ${money(quote.max_price)} per quintal`));
    const use = node('button','secondary-button',quote.stale ? 'Report too old to use' : `Use price for ${quote.crop}`);
    use.type = 'button'; use.disabled = quote.stale;
    use.addEventListener('click', () => {
      const input = document.querySelector(`tr[data-crop="${quote.crop}"] input[data-field="price_per_kg"]`);
      input.value = String(quote.price_per_kg); selectedQuotes[quote.crop] = quote; renderSelectedQuotes();
      use.textContent = 'Price filled · add yield and cost below';
    });
    card.append(use); list.append(card);
  });
  holder.append(list);
  nextOffset = data.next_offset; document.querySelector('#next-prices').hidden = nextOffset === null;
}

async function requestPrices(mode, offset=0) {
  const priceError = document.querySelector('#price-error'); priceError.hidden = true;
  const buttons = ['#fetch-prices','#import-prices','#next-prices'].map(id => document.querySelector(id));
  buttons.forEach(element => element.disabled = true);
  try {
    const filters = offset ? priceFilters : lookupFilters();
    if(!filters.state) throw new Error('Enter your state to find relevant mandi prices.');
    let response;
    if(mode === 'csv') {
      const file = document.querySelector('#price-csv').files[0];
      if(!file) throw new Error('Choose an official CSV export.');
      if(file.size > 2000000) throw new Error('CSV must be under 2 MB. Export a narrower date or location range.');
      if(!document.querySelector('#confirm-quintal').checked) throw new Error('Confirm that the export reports prices in rupees per quintal.');
      const body = new FormData(); Object.entries(filters).forEach(([key,value]) => body.append(key,value));
      body.append('file',file); body.append('portal',document.querySelector('#csv-source').value); body.append('confirmed_unit','INR/quintal');
      response = await fetch('/api/market-import',{method:'POST',body});
    } else {
      const query = new URLSearchParams({...filters,offset:String(offset)});
      response = await fetch(`/api/market-prices?${query}`);
    }
    const data = await response.json();
    if(!response.ok) throw new Error(data.error || 'Unable to load price reports.');
    priceFilters = filters; renderPriceReports(data);
  } catch(failure) {
    priceError.textContent = failure.message; priceError.hidden = false;
    document.querySelector('#price-results').replaceChildren(); document.querySelector('#next-prices').hidden = true;
  } finally {buttons.forEach(element => element.disabled = false);}
}

document.querySelector('#price-crop').addEventListener('change',updateCommodity);
document.querySelector('#fetch-prices').addEventListener('click',() => requestPrices('api'));
document.querySelector('#import-prices').addEventListener('click',() => requestPrices('csv'));
document.querySelector('#next-prices').addEventListener('click',() => requestPrices('api',nextOffset));
getMetadata(); getMarketStatus();
