# Dataset provenance

Crop Recommendation Dataset by Atharva Ingle:
https://www.kaggle.com/datasets/atharvaingle/crop-recommendation-dataset

The bundled CSV was downloaded from the public Harvestify mirror:
https://raw.githubusercontent.com/Gladiator07/Harvestify/master/Data-processed/crop_recommendation.csv

SHA-256: `808e1d84a544647f1ab2fdae04f434b1842692d6be09eee18a5c2d43eb78d77c`

2,200 rows, 22 crop labels, 100 rows per crop. Features: N, P, K,
temperature (°C), relative humidity (%), pH, rainfall (mm), and crop label.
N/P/K are dataset nutrient ratios; the dataset does not establish a conversion
from every laboratory's nutrient units. Match your soil test units before use.
The rainfall observation period is not specified in the CSV; align your inputs
with the dataset documentation before relying on predictions.

The Kaggle endpoint was inaccessible during development, so the original file
and current licensing could not be independently checked against Kaggle.
Verify original provenance and redistribution terms before public distribution.
No rows were synthesized or augmented. Market prices, yields, irrigation demand,
profit, geography, and season are absent from this training dataset. Financial
inputs and illustrative water categories are separate planning features.
