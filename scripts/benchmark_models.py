#!/usr/bin/env python3
"""Benchmark Kronos models on local machine."""
import time
import click
import pandas as pd
import numpy as np
import torch
from openstockagent.predictors.kronos_adapter import KronosStockPredictor


def make_test_data(n_days: int = 120):
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n_days, freq="B")
    return pd.DataFrame({
        "open": 100 + np.random.randn(n_days).cumsum(),
        "high": 101 + np.random.randn(n_days).cumsum(),
        "low": 99 + np.random.randn(n_days).cumsum(),
        "close": 100 + np.random.randn(n_days).cumsum(),
        "volume": np.random.randint(1000000, 10000000, n_days),
    }, index=dates)


@click.command()
@click.option("--variants", default="mini,small,base", help="Comma-separated model variants")
@click.option("--devices", default="cpu,mps", help="Comma-separated devices")
@click.option("--horizon", default=5, help="Prediction horizon")
@click.option("--n-days", default=120, help="Historical data length")
def main(variants: str, devices: str, horizon: int, n_days: int):
    df = make_test_data(n_days)
    click.echo(f"Test data: {len(df)} days, horizon={horizon}")
    click.echo(f"Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
    click.echo("")

    results = []
    for device in devices.split(","):
        device = device.strip()
        if device == "mps" and not torch.backends.mps.is_available():
            click.echo(f"[SKIP] MPS not available")
            continue

        for variant in variants.split(","):
            variant = variant.strip()
            click.echo(f"--- {variant.upper()} on {device.upper()} ---")

            # Load
            t0 = time.time()
            try:
                predictor = KronosStockPredictor(variant=variant, device=device)
            except Exception as e:
                click.echo(f"  LOAD FAIL: {e}")
                continue
            load_time = time.time() - t0
            click.echo(f"  Load: {load_time:.1f}s")

            # Warmup (MPS especially needs this)
            _ = predictor.predict("WARMUP", df.iloc[:30], horizon=horizon)

            # Predict
            t0 = time.time()
            result = predictor.predict("TEST", df, horizon=horizon)
            pred_time = time.time() - t0
            click.echo(f"  Predict: {pred_time:.1f}s")
            click.echo(f"  Confidence: {result.confidence:.4f}")
            click.echo(f"  Forecast close range: {result.forecast['close'].min():.2f} ~ {result.forecast['close'].max():.2f}")
            click.echo("")

            results.append({
                "variant": variant,
                "device": device,
                "load_time": load_time,
                "pred_time": pred_time,
                "confidence": result.confidence,
            })

    # Summary table
    click.echo("\n========== SUMMARY ==========")
    click.echo(f"{'Model':<10} {'Device':<6} {'Load(s)':<10} {'Predict(s)':<12} {'Confidence'}")
    click.echo("-" * 55)
    for r in results:
        click.echo(f"{r['variant']:<10} {r['device']:<6} {r['load_time']:<10.1f} {r['pred_time']:<12.1f} {r['confidence']:.4f}")


if __name__ == "__main__":
    main()
