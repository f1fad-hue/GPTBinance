#!/usr/bin/env python3
"""Robust 5%-grid portfolio optimizer with path-level drawdown controls."""
from __future__ import annotations

import itertools
import math
import random

MIN_WEIGHT = 5
WEIGHT_STEP = 5
BMNR_MAX_WEIGHT = 10
OPTIMIZATION_PATHS = 250
REPORTING_PATHS = 10_000
MONTHS = 120
MAX_BREACH_PROBABILITY = 0.10
FORECAST_PENALTY = 0.35
CORRELATION = (
    (1.00, .75, .05, .65),
    (.75, 1.00, .05, .55),
    (.05, .05, 1.00, .00),
    (.65, .55, .00, 1.00),
)
STRESS_SCENARIOS = (
    ("growth and rate shock", (-30.0, -18.0, 0.0, -55.0)),
    ("emerging-market and USD shock", (-12.0, -35.0, 0.0, -30.0)),
    ("digital-asset equity shock", (-15.0, -12.0, 0.0, -75.0)),
    ("broad liquidity shock", (-25.0, -25.0, 0.0, -60.0)),
)


def cap_from_rate(rate: float) -> float:
    return 30 if rate >= 5 else 25 if rate >= 4 else 20


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(probability * len(ordered)) - 1))]


def _cholesky(matrix: tuple[tuple[float, ...], ...]) -> list[list[float]]:
    size = len(matrix)
    result = [[0.0] * size for _ in range(size)]
    for row in range(size):
        for column in range(row + 1):
            subtotal = sum(result[row][k] * result[column][k] for k in range(column))
            if row == column:
                value = matrix[row][row] - subtotal
                if value <= 0:
                    raise ValueError("correlation matrix is not positive definite")
                result[row][column] = math.sqrt(value)
            else:
                result[row][column] = (matrix[row][column] - subtotal) / result[column][column]
    return result


def portfolio_path_stats(history: dict, weights: list[float]) -> dict:
    """Actual monthly-rebalanced portfolio MDD and 95% conditional drawdown."""
    target = [weight / 100 for weight in weights]
    live = target[:]
    wealth = peak = 1.0
    peak_date = history["returns"][0][0]
    worst = 0.0
    worst_peak = worst_trough = peak_date
    drawdowns = []
    previous_month = history["returns"][0][0][:7]
    for row in history["returns"]:
        observed, returns = row[0], row[1:]
        month = observed[:7]
        if month != previous_month:
            live = target[:]
            previous_month = month
        portfolio_return = sum(weight * value for weight, value in zip(live, returns))
        wealth *= 1 + portfolio_return
        gross = [weight * (1 + value) for weight, value in zip(live, returns)]
        total = sum(gross)
        live = [value / total for value in gross]
        if wealth > peak:
            peak = wealth
            peak_date = observed
        drawdown = max(0.0, 1 - wealth / peak)
        drawdowns.append(drawdown)
        if drawdown > worst:
            worst = drawdown
            worst_peak = peak_date
            worst_trough = observed
    tail_count = max(1, math.ceil(len(drawdowns) * .05))
    cdar95 = sum(sorted(drawdowns, reverse=True)[:tail_count]) / tail_count
    return {
        "maxDrawdown": round(worst * 100, 3), "cdar95": round(cdar95 * 100, 3),
        "peak": worst_peak, "trough": worst_trough,
    }


def _forecast_metrics(assets: list[dict], weights: list[float]) -> tuple[float, float, float]:
    fractions = [weight / 100 for weight in weights]
    net = sum(weight * (asset["grossCagr"] - asset["fee"]) for weight, asset in zip(fractions, assets))
    uncertainty = math.sqrt(sum((weight * asset["forecastUncertainty"]) ** 2 for weight, asset in zip(fractions, assets)))
    return net, uncertainty, net - FORECAST_PENALTY * uncertainty


def _portfolio_volatility(assets: list[dict], weights: list[float]) -> float:
    fractions = [weight / 100 for weight in weights]
    volatilities = [asset["vol"] / 100 for asset in assets]
    variance = sum(fractions[i] * fractions[j] * volatilities[i] * volatilities[j] * CORRELATION[i][j]
                   for i in range(len(assets)) for j in range(len(assets)))
    return math.sqrt(max(0.0, variance)) * 100


def _stress_stats(weights: list[float]) -> dict:
    fractions = [weight / 100 for weight in weights]
    losses = [{"name": name, "loss": round(-sum(weight * shock for weight, shock in zip(fractions, shocks)), 3)}
              for name, shocks in STRESS_SCENARIOS]
    worst = max(losses, key=lambda item: item["loss"])
    return {"worstLoss": worst["loss"], "worstScenario": worst["name"], "scenarios": losses}


def _shock_paths(assets: list[dict], count: int, seed: int, volatility_scale: float) -> list[list[list[float]]]:
    randomizer = random.Random(seed)
    cholesky = _cholesky(CORRELATION)
    annual_vol = [asset["vol"] / 100 * volatility_scale for asset in assets]
    annual_log_mean = [math.log1p((asset["grossCagr"] - asset["fee"]) / 100) for asset in assets]
    paths = []
    for _ in range(count):
        path = []
        for _month in range(MONTHS):
            independent = [randomizer.gauss(0, 1) for _ in assets]
            correlated = [sum(cholesky[row][column] * independent[column] for column in range(row + 1)) for row in range(len(assets))]
            fat_tail_scale = 1.75 if randomizer.random() < .04 else 1.0
            returns = []
            for index in range(len(assets)):
                sigma = annual_vol[index] / math.sqrt(12)
                log_return = annual_log_mean[index] / 12 - .5 * sigma * sigma + sigma * correlated[index] * fat_tail_scale
                returns.append(max(-.95, math.exp(log_return) - 1))
            path.append(returns)
        paths.append(path)
    return paths


def _simulation_stats(paths: list[list[list[float]]], weights: list[float], cap: float) -> dict:
    fractions = [weight / 100 for weight in weights]
    terminals, max_drawdowns = [], []
    for path in paths:
        wealth = peak = 1.0
        worst = 0.0
        for returns in path:
            wealth *= 1 + sum(weight * value for weight, value in zip(fractions, returns))
            peak = max(peak, wealth)
            worst = max(worst, 1 - wealth / peak)
        terminals.append(wealth)
        max_drawdowns.append(worst * 100)
    breaches = sum(value > cap + 1e-9 for value in max_drawdowns)
    return {
        "paths": len(paths), "years": 10,
        "p10Terminal": round(_percentile(terminals, .10), 3),
        "p50Terminal": round(_percentile(terminals, .50), 3),
        "p90Terminal": round(_percentile(terminals, .90), 3),
        "medianMaxDrawdown": round(_percentile(max_drawdowns, .50), 3),
        "p90MaxDrawdown": round(_percentile(max_drawdowns, .90), 3),
        "breachProbability": round(breaches / len(paths), 4),
    }


def _grid(asset_count: int):
    units = (100 - MIN_WEIGHT * asset_count) // WEIGHT_STEP
    for prefix in itertools.product(range(units + 1), repeat=asset_count - 1):
        used = sum(prefix)
        if used > units:
            continue
        extras = (*prefix, units - used)
        weights = [MIN_WEIGHT + WEIGHT_STEP * value for value in extras]
        if weights[-1] <= BMNR_MAX_WEIGHT:
            yield weights


def optimize_scenario(assets: list[dict], history: dict, rate: int) -> dict:
    cap = cap_from_rate(rate)
    candidates = []
    for weights in _grid(len(assets)):
        observed = portfolio_path_stats(history, weights)
        stress = _stress_stats(weights)
        if observed["maxDrawdown"] > cap + 1e-9 or stress["worstLoss"] > cap + 1e-9:
            continue
        net, uncertainty, robust = _forecast_metrics(assets, weights)
        portfolio_volatility = _portfolio_volatility(assets, weights)
        if portfolio_volatility > cap / 2.6:
            continue
        candidates.append((robust, net, -stress["worstLoss"], weights, observed, stress, uncertainty, portfolio_volatility))
    candidates.sort(reverse=True, key=lambda item: item[:3])
    volatility_scale = {3: 1.15, 4: 1.0, 5: .90}[rate]
    optimization_paths = _shock_paths(assets, OPTIMIZATION_PATHS, 8100 + rate, volatility_scale)
    selected = None
    reporting_paths = None
    for robust, net, _risk_tie, weights, observed, stress, uncertainty, portfolio_volatility in candidates:
        simulation = _simulation_stats(optimization_paths, weights, cap)
        if simulation["breachProbability"] > MAX_BREACH_PROBABILITY - .02:
            continue
        if reporting_paths is None:
            reporting_paths = _shock_paths(assets, REPORTING_PATHS, 9100 + rate, volatility_scale)
        reporting = _simulation_stats(reporting_paths, weights, cap)
        if reporting["breachProbability"] <= MAX_BREACH_PROBABILITY + 1e-9:
            selected = (weights, observed, stress, net, uncertainty, robust, portfolio_volatility, reporting)
            break
    if selected is None:
        raise RuntimeError(f"no robust allocation satisfies the rate-{rate} drawdown controls")
    weights, observed, stress, net, uncertainty, robust, portfolio_volatility, simulation = selected
    return {
        "rate": rate, "cap": cap, "weights": dict(zip([asset["ticker"] for asset in assets], weights)),
        "netCagrForecast": round(net, 3), "forecastUncertainty": round(uncertainty, 3),
        "robustGrowthScore": round(robust, 3), "modeledVolatility": round(portfolio_volatility, 3), "observedPortfolio": observed,
        "stress": stress, "simulation": simulation,
    }


def build_model(payload: dict, history: dict) -> dict:
    scenarios = {str(rate): optimize_scenario(payload["assets"], history, rate) for rate in (3, 4, 5)}
    return {
        "method": "robust-path-growth-v1", "objective": "net CAGR forecast minus 35% of forecast uncertainty",
        "constraints": {
            "minimumWeight": MIN_WEIGHT, "weightStep": WEIGHT_STEP, "bmnrMaximumWeight": BMNR_MAX_WEIGHT,
            "maximumDrawdownBreachProbability": MAX_BREACH_PROBABILITY,
            "observedPortfolioPath": True, "monthlyRebalance": True,
        },
        "correlation": [list(row) for row in CORRELATION],
        "correlationLabel": "conservative model assumption; monitored against synchronized authoritative histories",
        "stressScenarios": [{"name": name, "shocks": dict(zip([asset["ticker"] for asset in payload["assets"]], shocks))} for name, shocks in STRESS_SCENARIOS],
        "history": history, "scenarios": scenarios,
    }
