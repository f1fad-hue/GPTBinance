const pct = n => `${n.toFixed(1)}%`;
const $ = s => document.querySelector(s);
const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
const TICKERS = ['QQQ', 'IEMG', 'SGOV', 'BMNR'];
const DRIVER_EXPOSURE = {
  'Inflation trend':[.85,.70,.95,.65], 'Policy rates':[.95,.60,1,.80], 'Real yields':[1,.70,.90,.85], 'Yield curve':[.75,.60,.80,.55],
  'Credit spreads':[.70,.75,.25,.80], 'Labor & activity':[.80,.65,.30,.55], 'Financial conditions':[.90,.80,.45,1], 'System liquidity':[.90,.75,.35,1],
  'Market volatility':[.85,.80,.45,1], 'USD / EM FX trend':[.45,1,.40,.65], 'Industrial production':[.65,.90,.25,.45], 'Bank lending standards':[.60,.65,.30,.70],
  'Nominal Treasury yields':[.95,.55,1,.65], 'Inflation expectations':[.85,.65,.90,.65], 'Payroll momentum':[.75,.55,.25,.45], 'Real consumer demand':[.80,.60,.25,.50]
};
const REGION_DRIVER_WEIGHTS = {
  US:{'Inflation trend':.8,'Policy rates':1,'Real yields':1,'Yield curve':.8,'Credit spreads':.8,'Labor & activity':.9,'Financial conditions':1,'System liquidity':.9,'Market volatility':.8,'Nominal Treasury yields':1,'Inflation expectations':.8,'Payroll momentum':.9,'Real consumer demand':.9},
  Europe:{'Inflation trend':.6,'Policy rates':.5,'Real yields':.6,'Yield curve':.5,'Credit spreads':.8,'Labor & activity':.6,'Financial conditions':.9,'System liquidity':.7,'Market volatility':.8,'USD / EM FX trend':.8,'Industrial production':.8,'Bank lending standards':.7,'Nominal Treasury yields':.5,'Inflation expectations':.6,'Real consumer demand':.7},
  Asia:{'Inflation trend':.6,'Policy rates':.5,'Real yields':.5,'Yield curve':.5,'Credit spreads':.7,'Labor & activity':.6,'Financial conditions':.9,'System liquidity':.8,'Market volatility':.9,'USD / EM FX trend':1,'Industrial production':1,'Bank lending standards':.6,'Nominal Treasury yields':.5,'Inflation expectations':.6,'Payroll momentum':.5,'Real consumer demand':.8}
};

async function main() {
  const response = await fetch('data/market-data.json', { cache: 'no-store' });
  if (!response.ok) throw new Error(`Market data request failed (${response.status})`);
  const data = await response.json();
  const assets = data.assets;
  const scenarioModel = data.model.scenarios;
  const scenarios = Object.fromEntries([3, 4, 5].map(rate => [rate, assets.map(asset => scenarioModel[rate].weights[asset.ticker])]));
  const signal = selectRate(data.macro, assets, scenarios);
  const { rate, weights, broad, correlated, regional } = signal;
  const cap = capFromRate(rate);
  const band = rate >= 5 ? 5 : rate >= 4 ? 4 : 3;
  const activeModel = scenarioModel[band];
  const allocation = assets.map((x, i) => ({ ...x, weight: weights[i] }));
  const cagr = activeModel.netCagrForecast;
  const dd = activeModel.observedPortfolio.maxDrawdown;
  if (dd > cap + 1e-9 || activeModel.stress.worstLoss > cap + 1e-9 || activeModel.simulation.breachProbability > data.model.constraints.maximumDrawdownBreachProbability + .015) {
    throw new Error(`Robust drawdown controls failed for rate ${band}`);
  }

  $('#portfolio-rate').textContent = rate.toFixed(2);
  $('#rate-copy').textContent = rate >= 4
    ? 'Constructive macro signal; growth tilt remains bounded by the drawdown rule.'
    : 'Mixed macro signal; the model requires a stricter drawdown cap.';
  $('#rate-meter').style.width = `${rate * 20}%`;
  $('#cagr').textContent = pct(cagr);
  $('#drawdown').textContent = pct(dd);
  $('#dd-cap').textContent = pct(cap);
  $('#stress-dd').textContent = pct(activeModel.stress.worstLoss);
  $('#breach-risk').textContent = `${(activeModel.simulation.breachProbability * 100).toFixed(1)}%`;
  $('#asof-chip').textContent = `As of ${data.asOf}`;
  $('#validated-at').textContent = new Date(data.validation.checkedAt).toLocaleString();
  $('#validation-status').textContent = data.validation.status;

  $('#allocation').innerHTML = allocation.map(x => `<article class="allocation"><b>${x.weight.toFixed(0)}%</b><span>${x.ticker} · ${x.class}</span><i style="width:${Math.min(100, x.weight / 65 * 100)}%"></i></article>`).join('');
  const scoreCards = scores => ['m3','m6','m12'].map((key, index) => `<div class="horizon-score"><span>${[3,6,12][index]} months</span><b>${scores[key].toFixed(2)} / 5</b></div>`).join('');
  $('#broad-sentiment').innerHTML = scoreCards(broad);
  $('#correlated-sentiment').innerHTML = scoreCards(correlated);
  $('#heatmap').innerHTML = '<div class="label">Driver / horizon</div><div class="label">3M</div><div class="label">6M</div><div class="label">12M</div>' + data.macro.map(x => `<div class="label driver"><b>${x.driver}</b><small>${x.why}</small></div>${[x.m3, x.m6, x.m12].map(v => `<div class="${v >= 3.7 ? 'good' : v >= 3.3 ? 'mixed' : 'bad'}">${v.toFixed(1)} / 5</div>`).join('')}`).join('');
  $('#regional-ranking').innerHTML = regional.map(x => `<article class="region-card"><strong>#${x.rank} ${x.region}</strong><span>Average</span><b>${x.average.toFixed(2)} / 5</b><small>3M ${x.m3.toFixed(2)} · 6M ${x.m6.toFixed(2)} · 12M ${x.m12.toFixed(2)}</small></article>`).join('');

  const overlay = data.bmnrOverlay;
  $('#bmnr-overlay').innerHTML = `<h2>BMNR digital-asset overlay</h2><p><b>${overlay.score.toFixed(1)} / 5 — ${overlay.status}</b><br>${overlay.current}</p><p class="caption"><strong>Triggers:</strong> ${overlay.triggers}<br><strong>Review:</strong> ${overlay.cadence} <a href="${overlay.source}" target="_blank" rel="noreferrer">SEC filings</a></p>`;

  const donutColors = ['#3de0b5', '#54a9ff', '#8e8bff', '#ffc75a'];
  $('#donuts').innerHTML = [3, 4, 5].map(s => {
    let p = 0;
    const stops = scenarios[s].map((w, i) => {
      const start = p;
      p += w;
      return `${donutColors[i]} ${start}% ${p}%`;
    }).join(',');
    const summary = assets.map((a, i) => `${a.ticker} ${scenarios[s][i].toFixed(0)}%`).join(' · ');
    const labels = assets.map((a, i) => `<span class="slice-label"><i style="background:${donutColors[i]}"></i>${a.ticker} ${scenarios[s][i].toFixed(0)}%</span>`).join('');
    const scenario = scenarioModel[s];
    return `<article class="donut-card"><div class="donut" role="img" aria-label="Rate ${s.toFixed(2)} allocation: ${summary}" style="background:conic-gradient(${stops})"></div><h3>Rate ${s.toFixed(2)}</h3><p class="donut-labels">${labels}</p><small class="scenario-math">Net CAGR ${pct(scenario.netCagrForecast)} · observed DD ${pct(scenario.observedPortfolio.maxDrawdown)} · simulated breach ${(scenario.simulation.breachProbability * 100).toFixed(1)}%</small></article>`;
  }).join('');

  const sims = activeModel.simulation;
  $('#mc-p50').textContent = pct((Math.pow(sims.p50Terminal, 1 / 10) - 1) * 100);
  $('#mc-note').textContent = `${sims.paths.toLocaleString()} correlated paths · $1 P50 $${sims.p50Terminal.toFixed(2)}`;
  const terminalValues = [['P10', sims.p10Terminal], ['P50', sims.p50Terminal], ['P90', sims.p90Terminal]];
  $('#fan-chart').innerHTML = terminalValues.map(([label, value]) => `<div class="terminal-bar"><i style="height:${value / sims.p90Terminal * 100}%"></i><b>${label}</b><span>$${value.toFixed(2)}</span></div>`).join('');
  $('#risk-summary').textContent = `Observed monthly-rebalanced MDD ${pct(dd)} (${activeModel.observedPortfolio.peak} to ${activeModel.observedPortfolio.trough}); 95% conditional observed drawdown ${pct(activeModel.observedPortfolio.cdar95)}. The worst named stress is ${activeModel.stress.worstScenario} at ${pct(activeModel.stress.worstLoss)}. Across 10-year simulations, median MDD is ${pct(sims.medianMaxDrawdown)}, P90 MDD is ${pct(sims.p90MaxDrawdown)}, and ${(sims.breachProbability * 100).toFixed(1)}% of paths exceed the ${cap}% cap.`;

  $('#slides').innerHTML = allocation.map(x => `<article class="slide"><span class="ticker">${x.ticker}</span><h3>${x.name}</h3><div class="metrics"><div><span>Observed max DD</span><b>${pct(x.historicalDD)}</b></div><div><span>Forecast net 10Y CAGR</span><b>${pct(x.grossCagr - x.fee)}</b></div><div><span>Fund fee</span><b>${pct(x.fee)}</b></div><div><span>Portfolio weight</span><b>${x.weight.toFixed(0)}%</b></div></div><p class="risk"><strong>Observed period:</strong> ${x.historicalDDStart} to ${x.historicalDDEnd}<br><strong>Peak → trough:</strong> ${x.historicalDDPeak} → ${x.historicalDDTrough}</p><p class="risk">Forecast return is a model assumption. Historical max DD is the sole cap input, not a forecast.</p><p class="risk">${x.history}</p><p class="risk"><strong>Role:</strong> ${x.reason}</p></article>`).join('');

  const weightOf = ticker => allocation.find(x => x.ticker === ticker).weight.toFixed(0);
  $('#rationale').textContent = `The robust growth model places ${weightOf('QQQ')}% in Nasdaq-100 growth, ${weightOf('IEMG')}% in emerging markets, ${weightOf('SGOV')}% in Treasury bills, and ${weightOf('BMNR')}% in the single-stock satellite. It searches every valid 5% allocation and maximizes the 10-year net-CAGR forecast after an uncertainty penalty. The selected allocation must pass the observed combined-portfolio path, four simultaneous stress scenarios, and a correlated 10-year drawdown-breach test under the ${cap}% rate-band cap. BMNR is limited to 10%. This is a hypothetical model, not investment advice or a guarantee.`;

  $('#monitoring').innerHTML = assets.map(x => `<tr><td><b>${x.ticker}</b></td><td><span class="status ${x.monitorStatus.toLowerCase().replace(' ', '-')}">${x.monitorStatus}</span><br><span class="muted">${x.monitorNote}</span></td><td>${x.relevance}/100</td><td>${x.notRelevant}</td><td>${x.cadence}</td></tr>`).join('');
  const uniqueSources = [...new Map(data.sources.map(source => [source.url, source])).values()];
  $('#sources').innerHTML = '<ul>' + uniqueSources.map(s => `<li><a href="${s.url}" target="_blank" rel="noreferrer">${s.name}</a></li>`).join('') + '</ul>';
  $('#refresh').onclick = () => location.reload();
  document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.toggle('active', x === button));
    document.querySelectorAll('.page').forEach(x => x.classList.toggle('active', x.dataset.page === button.dataset.tab));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }));
}

function horizonScores(macro, driverWeights = null) {
  const weights = driverWeights || Object.fromEntries(macro.map(item => [item.driver, 1]));
  const total = macro.reduce((sum, item) => sum + (weights[item.driver] || 0), 0);
  return Object.fromEntries(['m3','m6','m12'].map(key => [key, +(macro.reduce((sum, item) => sum + item[key] * (weights[item.driver] || 0), 0) / total).toFixed(2)]));
}

function sentimentOutputs(macro, assets, weights) {
  const broad = horizonScores(macro);
  const tickerIndex = Object.fromEntries(TICKERS.map((ticker, index) => [ticker, index]));
  const transmission = Object.fromEntries(Object.entries(DRIVER_EXPOSURE).map(([driver, exposure]) => [driver, TICKERS.reduce((sum, ticker) => sum + weights[tickerIndex[ticker]] * exposure[tickerIndex[ticker]] / 100, 0)]));
  const correlated = horizonScores(macro, transmission);
  const regional = Object.entries(REGION_DRIVER_WEIGHTS).map(([region, regionWeights]) => {
    const scores = horizonScores(macro, regionWeights);
    return { region, ...scores, average: +((scores.m3 + scores.m6 + scores.m12) / 3).toFixed(2) };
  }).sort((a, b) => b.average - a.average || a.region.localeCompare(b.region));
  regional.forEach((item, index) => item.rank = index + 1);
  return { broad, correlated, regional };
}

function selectRate(macro, assets, scenarios) {
  let band = 4;
  const seen = [];
  while (!seen.includes(band)) {
    seen.push(band);
    const weights = scenarios[band];
    const outputs = sentimentOutputs(macro, assets, weights);
    const broadAvg = (outputs.broad.m3 + outputs.broad.m6 + outputs.broad.m12) / 3;
    const correlatedAvg = (outputs.correlated.m3 + outputs.correlated.m6 + outputs.correlated.m12) / 3;
    const rate = +clamp(.40 * broadAvg + .60 * correlatedAvg, 1, 5).toFixed(2);
    const nextBand = rate >= 5 ? 5 : rate >= 4 ? 4 : 3;
    if (nextBand === band) return { rate, weights, ...outputs };
    band = nextBand;
  }
  band = Math.min(seen.at(-1), band);
  const weights = scenarios[band];
  const outputs = sentimentOutputs(macro, assets, weights);
  let rate = +clamp(.40 * (outputs.broad.m3 + outputs.broad.m6 + outputs.broad.m12) / 3 + .60 * (outputs.correlated.m3 + outputs.correlated.m6 + outputs.correlated.m12) / 3, 1, 5).toFixed(2);
  rate = band === 3 ? Math.min(rate, 3.99) : band === 4 ? Math.min(Math.max(rate, 4), 4.99) : 5;
  return { rate, weights, ...outputs };
}

function capFromRate(rate) {
  return rate >= 5 ? 30 : rate >= 4 ? 25 : 20;
}

if (typeof document !== 'undefined') {
  main().catch(error => {
    document.body.innerHTML = `<main><h1>Data load error</h1><p>${error.message}</p></main>`;
  });
}
if (typeof module !== 'undefined') module.exports = { capFromRate, horizonScores, sentimentOutputs, selectRate, TICKERS };
