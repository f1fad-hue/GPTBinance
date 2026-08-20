const fs = require('node:fs');
const path = require('node:path');
const model = require('../app.js');

const root = path.resolve(__dirname, '..');
const data = JSON.parse(fs.readFileSync(path.join(root, 'data', 'market-data.json'), 'utf8'));
const tickers = data.assets.map(asset => asset.ticker);
if (JSON.stringify(tickers) !== JSON.stringify(model.TICKERS)) throw new Error(`Holding order mismatch: ${tickers.join(', ')}`);
if (model.capFromRate(3.99) !== 20 || model.capFromRate(4) !== 25 || model.capFromRate(4.99) !== 25 || model.capFromRate(5) !== 30) throw new Error('Rate-cap boundary validation failed');
if (data.model.method !== 'robust-path-growth-v1') throw new Error('Robust model payload is missing');

const scenarios = {};
for (const rate of [3, 4, 5]) {
  const scenario = data.model.scenarios[rate];
  const weights = tickers.map(ticker => scenario.weights[ticker]);
  scenarios[rate] = weights;
  if (weights.reduce((sum, value) => sum + value, 0) !== 100 || weights.some(value => value < 5 || value % 5)) throw new Error(`Invalid rate-${rate} allocation grid`);
  if (scenario.weights.BMNR > data.model.constraints.bmnrMaximumWeight) throw new Error(`Rate-${rate} BMNR concentration limit failed`);
  if (scenario.observedPortfolio.maxDrawdown > scenario.cap || scenario.stress.worstLoss > scenario.cap) throw new Error(`Rate-${rate} path/stress cap failed`);
  if (scenario.simulation.paths !== 10000 || scenario.simulation.years !== 10) throw new Error(`Rate-${rate} simulation size failed`);
  if (scenario.simulation.breachProbability > data.model.constraints.maximumDrawdownBreachProbability + .015) throw new Error(`Rate-${rate} simulated breach constraint failed`);
}
const signal = model.selectRate(data.macro, data.assets, scenarios);
if (!Number.isFinite(signal.rate) || signal.rate < 1 || signal.rate > 5 || signal.rate !== +signal.rate.toFixed(2)) throw new Error('Two-decimal rate validation failed');
if (signal.regional.length !== 3 || new Set(signal.regional.map(item => item.region)).size !== 3) throw new Error('Regional ranking validation failed');
console.log(`PASS — browser model parity; rate ${signal.rate.toFixed(2)}; robust scenarios 3/4/5 verified`);
