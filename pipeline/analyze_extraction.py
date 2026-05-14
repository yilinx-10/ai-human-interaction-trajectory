"""
Analyze how conversation traits affect extraction time and performance.
Optionally compare two models side-by-side.

Usage:
    # Single model analysis
    python -m pipeline.analyze_extraction --files processed_teammate/standard_export/layer_belief_sonnet_timing.json

    # Model comparison (sonnet vs haiku)
    python -m pipeline.analyze_extraction \
        --files processed_teammate/standard_export/layer_belief_sonnet_timing.json \
                processed_teammate/standard_export/layer_belief_haiku_timing.json \
        --labels sonnet haiku
"""

import argparse
import json
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="use_inf_as_na option is deprecated")

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats


TRAITS = ["total_turn_count", "total_chars", "approx_tokens", "truncated"]
OUTCOMES = ["processing_time_s", "nodes_extracted", "edges_extracted"]
TRAIT_LABELS = {
    "total_turn_count": "Turn count",
    "total_chars": "Length (chars)",
    "approx_tokens": "Approx tokens",
    "truncated": "Truncated",
}
OUTCOME_LABELS = {
    "processing_time_s": "Processing time (s)",
    "nodes_extracted": "Nodes extracted",
    "edges_extracted": "Edges extracted",
}


def load_timing(path: str) -> tuple[pd.DataFrame, dict]:
    with open(path) as f:
        data = json.load(f)
    run_meta = data["run"]
    df = pd.DataFrame(data["conversations"])
    df["model"] = run_meta.get("model", Path(path).stem)
    # Drop rows that errored out (0 nodes AND 0 edges with an error field)
    df = df[~((df["nodes_extracted"] == 0) & (df["edges_extracted"] == 0) & df["error"].notna())]
    df["truncated"] = df["truncated"].astype(int)
    return df, run_meta


def print_summary(df: pd.DataFrame, run_meta: dict, label: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {label}  |  model: {run_meta.get('model')}  |  n={len(df)}")
    print(f"  total_time={run_meta.get('total_time_s', 0):.1f}s  "
          f"avg={run_meta.get('avg_time_per_conv_s', 0):.1f}s  "
          f"min={run_meta.get('min_time_s', 0):.1f}s  "
          f"max={run_meta.get('max_time_s', 0):.1f}s")
    print(f"{'='*60}")
    summary = df[TRAITS + OUTCOMES].describe().loc[["mean", "std", "min", "max"]].round(2)
    print(summary.to_string())


def correlation_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for trait in TRAITS:
        for outcome in OUTCOMES:
            x, y = df[trait].values, df[outcome].values
            if len(x) < 3:
                rows.append({"trait": trait, "outcome": outcome, "r": np.nan, "p": np.nan})
                continue
            r, p = stats.pearsonr(x, y)
            rows.append({"trait": trait, "outcome": outcome, "r": round(r, 3), "p": round(p, 4)})
    return pd.DataFrame(rows)


def plot_scatter_grid(df: pd.DataFrame, label: str, out_path: Path) -> None:
    continuous = ["total_turn_count", "total_chars", "approx_tokens"]
    fig, axes = plt.subplots(len(continuous), len(OUTCOMES), figsize=(14, 9))
    fig.suptitle(f"Conversation traits vs. extraction outcomes  [{label}]", fontsize=13)

    for row_i, trait in enumerate(continuous):
        for col_j, outcome in enumerate(OUTCOMES):
            ax = axes[row_i][col_j]
            colors = ["#e07b54" if t else "#5b9bd5" for t in df["truncated"]]
            ax.scatter(df[trait], df[outcome], c=colors, alpha=0.7, s=40, edgecolors="none")
            # Fit line
            x, y = df[trait].values, df[outcome].values
            if len(x) >= 3:
                m, b, r, p, _ = stats.linregress(x, y)
                xr = np.linspace(x.min(), x.max(), 100)
                ax.plot(xr, m * xr + b, color="#333", linewidth=1.2, alpha=0.6)
                stars = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
                ax.set_title(f"r={r:.2f}{stars}", fontsize=9)
            ax.set_xlabel(TRAIT_LABELS[trait], fontsize=8)
            ax.set_ylabel(OUTCOME_LABELS[outcome], fontsize=8)
            ax.tick_params(labelsize=7)

    # Legend for truncated
    from matplotlib.lines import Line2D
    legend = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#e07b54", markersize=7, label="truncated"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#5b9bd5", markersize=7, label="full"),
    ]
    fig.legend(handles=legend, loc="lower right", fontsize=8)
    fig.tight_layout(rect=[0, 0.02, 1, 0.97])
    fig.savefig(out_path, dpi=150)
    print(f"  Saved: {out_path}")


def plot_truncated_comparison(df: pd.DataFrame, label: str, out_path: Path) -> None:
    df_plot = df.copy()
    df_plot["truncated_label"] = df_plot["truncated"].map({0: "full", 1: "truncated"})
    palette = {"full": "#5b9bd5", "truncated": "#e07b54"}

    fig, axes = plt.subplots(1, len(OUTCOMES), figsize=(12, 5))
    fig.suptitle(f"Truncated vs. full conversations  [{label}]", fontsize=12)

    for i, outcome in enumerate(OUTCOMES):
        ax = axes[i]
        sns.swarmplot(data=df_plot, x="truncated_label", y=outcome, hue="truncated_label",
                      order=["full", "truncated"], hue_order=["full", "truncated"],
                      palette=palette, size=5, alpha=0.8, legend=False, ax=ax)
        # Median line per group
        for j, grp in enumerate(["full", "truncated"]):
            med = df_plot[df_plot["truncated_label"] == grp][outcome].median()
            ax.plot([j - 0.3, j + 0.3], [med, med], color="#333", linewidth=1.8, solid_capstyle="round")
        ax.set_title(OUTCOME_LABELS[outcome], fontsize=9)
        ax.set_xlabel("")
        ax.tick_params(labelsize=8)

        tv = df[df["truncated"] == 1][outcome].values
        fv = df[df["truncated"] == 0][outcome].values
        if len(tv) >= 3 and len(fv) >= 3:
            _, p = stats.mannwhitneyu(tv, fv, alternative="two-sided")
            stars = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else f"p={p:.2f}"
            ax.set_xlabel(f"Mann-Whitney {stars}", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"  Saved: {out_path}")


def plot_model_comparison(dfs: list[pd.DataFrame], labels: list[str], out_path: Path) -> None:
    colors = ["#5b9bd5", "#e07b54", "#6abf69", "#b39ddb"]
    palette = dict(zip(labels, colors))

    combined = pd.concat(
        [df.assign(model_label=lbl) for df, lbl in zip(dfs, labels)],
        ignore_index=True,
    )

    fig, axes = plt.subplots(1, len(OUTCOMES), figsize=(14, 5))
    fig.suptitle("Model comparison: " + " vs. ".join(labels), fontsize=12)

    for col_j, outcome in enumerate(OUTCOMES):
        ax = axes[col_j]
        sns.swarmplot(data=combined, x="model_label", y=outcome, hue="model_label",
                      order=labels, hue_order=labels,
                      palette=palette, size=5, alpha=0.8, legend=False, ax=ax)
        # Median lines
        for j, lbl in enumerate(labels):
            med = combined[combined["model_label"] == lbl][outcome].median()
            ax.plot([j - 0.3, j + 0.3], [med, med], color="#333", linewidth=1.8, solid_capstyle="round")
        ax.set_title(OUTCOME_LABELS[outcome], fontsize=9)
        ax.set_xlabel("")
        ax.tick_params(labelsize=8)

        if len(dfs) == 2 and len(dfs[0]) >= 3 and len(dfs[1]) >= 3:
            _, p = stats.mannwhitneyu(dfs[0][outcome].values, dfs[1][outcome].values, alternative="two-sided")
            stars = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else f"p={p:.2f}"
            ax.set_xlabel(f"Mann-Whitney {stars}", fontsize=8)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"  Saved: {out_path}")


def plot_scatter_overlay(dfs: list[pd.DataFrame], labels: list[str], out_path: Path) -> None:
    """Overlay scatter of processing_time vs token count for each model."""
    fig, axes = plt.subplots(1, len(OUTCOMES), figsize=(14, 5))
    fig.suptitle("Processing traits by model: " + " vs. ".join(labels), fontsize=12)
    colors = ["#5b9bd5", "#e07b54"]
    markers = ["o", "s"]

    for col_j, outcome in enumerate(OUTCOMES):
        ax = axes[col_j]
        for df, label, color, marker in zip(dfs, labels, colors, markers):
            ax.scatter(df["approx_tokens"], df[outcome], label=label,
                       color=color, alpha=0.6, s=40, marker=marker, edgecolors="none")
            x, y = df["approx_tokens"].values, df[outcome].values
            if len(x) >= 3:
                m, b, r, p, _ = stats.linregress(x, y)
                xr = np.linspace(x.min(), x.max(), 100)
                ax.plot(xr, m * xr + b, color=color, linewidth=1.5, linestyle="--", alpha=0.7)
        ax.set_xlabel("Approx tokens", fontsize=8)
        ax.set_ylabel(OUTCOME_LABELS[outcome], fontsize=8)
        ax.set_title(OUTCOME_LABELS[outcome], fontsize=9)
        ax.legend(fontsize=7)
        ax.tick_params(labelsize=7)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"  Saved: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze belief extraction timing data")
    parser.add_argument("--files", nargs="+", required=True,
                        help="One or two *_timing.json paths")
    parser.add_argument("--labels", nargs="+", default=None,
                        help="Human-readable labels for each file (default: model name from JSON)")
    parser.add_argument("--out-dir", default="analysis_output",
                        help="Directory to write plots (default: analysis_output/)")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    loaded = [load_timing(f) for f in args.files]
    dfs = [item[0] for item in loaded]
    metas = [item[1] for item in loaded]
    labels = args.labels if args.labels else [df["model"].iloc[0] for df in dfs]

    # --- Per-model analysis ---
    for df, meta, label in zip(dfs, metas, labels):
        slug = label.replace(" ", "_")
        print_summary(df, meta, label)

        print(f"\n[{label}] Pearson correlation table (traits → outcomes):")
        corr = correlation_table(df)
        pivot = corr.pivot(index="trait", columns="outcome", values="r")
        pivot.index = [TRAIT_LABELS[t] for t in pivot.index]
        pivot.columns = [OUTCOME_LABELS[o] for o in pivot.columns]
        print(pivot.round(3).to_string())

        print(f"\n[{label}] p-values:")
        piv_p = corr.pivot(index="trait", columns="outcome", values="p")
        piv_p.index = [TRAIT_LABELS[t] for t in piv_p.index]
        piv_p.columns = [OUTCOME_LABELS[o] for o in piv_p.columns]
        print(piv_p.round(4).to_string())

        plot_scatter_grid(df, label, out_dir / f"scatter_{slug}.png")
        plot_truncated_comparison(df, label, out_dir / f"truncated_{slug}.png")

    # --- Cross-model comparison (if 2+ files) ---
    if len(dfs) >= 2:
        print("\n\n[Model comparison]")
        for outcome in OUTCOMES:
            means = [df[outcome].mean() for df in dfs]
            stds  = [df[outcome].std()  for df in dfs]
            for label, m, s in zip(labels, means, stds):
                print(f"  {label:20s}  {OUTCOME_LABELS[outcome]:25s}  mean={m:.2f}  std={s:.2f}")
        plot_model_comparison(dfs, labels, out_dir / "model_comparison.png")
        plot_scatter_overlay(dfs, labels, out_dir / "model_overlay.png")

    print(f"\nAll plots written to: {out_dir}/")


if __name__ == "__main__":
    main()
