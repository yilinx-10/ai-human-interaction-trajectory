"""
Analyze semantic content of belief graphs: node types, edge types/schemes,
co-constructed nodes, tension edges, and cluster tree depth.

Schema (from beliefs.py SYSTEM_PROMPT):
  Node types  : claim | evidence | constraint | conclusion
  Node origins: user | model | co-constructed
  Edge relations: supports | tension
  supports → scheme      : causal | evidential | expert | analogical |
                            consequence | example | other
  tension  → attack_type : rebutting | undercutting
  (old data may store attack_type inside the `scheme` field)

Usage:
    python -m pipeline.analyze_belief_content \
        --haiku  frontend/public/data/donghua-haiku-100/layer_belief_haiku.json \
                 frontend/public/data/donghua-haiku-100/layer_topic.json \
        --sonnet processed_teammate/standard_export/layer_belief_sonnet.json \
                 processed_teammate/standard_export/layer_topic.json \
        --out-dir analysis_output
"""

import argparse
import json
import warnings
from collections import Counter, defaultdict
from pathlib import Path

warnings.filterwarnings("ignore", message="use_inf_as_na option is deprecated")

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from scipy import stats


# ── schema constants ──────────────────────────────────────────────────────────

NODE_TYPES    = ["claim", "evidence", "constraint", "conclusion"]
NODE_ORIGINS  = ["user", "model", "co-constructed"]
EDGE_RELS     = ["supports", "tension"]
SUPPORT_SCHEMES = ["causal", "evidential", "expert", "analogical",
                   "consequence", "example", "other"]
ATTACK_TYPES  = ["rebutting", "undercutting"]

# Values that look like attack_type but may appear in the `scheme` field of
# old data that predates the schema split.
_ATTACK_ALIASES = set(ATTACK_TYPES) | {"undercutting", "rebutting"}


# ── helpers ───────────────────────────────────────────────────────────────────

def load_belief(path: str) -> list[dict]:
    with open(path) as f:
        d = json.load(f)
    return d["per_conversation"]


def load_topic(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _canonical(value: str | None, valid: list[str]) -> tuple[str, bool]:
    """Return (value, is_canonical).  None → ('missing', False)."""
    if value is None:
        return "missing", False
    return value, value in valid


def tree_max_depth(node: dict, cur: int = 0) -> int:
    if not node.get("children"):
        return cur
    return max(tree_max_depth(c, cur + 1) for c in node["children"])


def collect_tree_nodes(node: dict, acc: list | None = None) -> list[dict]:
    if acc is None:
        acc = []
    acc.append(node)
    for c in node.get("children", []):
        collect_tree_nodes(c, acc)
    return acc


# ── per-dataset stats ─────────────────────────────────────────────────────────

def compute_belief_stats(convs: list[dict]) -> dict:
    node_types   = Counter()   # canonical only
    node_origins = Counter()   # canonical only
    node_type_offschema   = Counter()
    node_origin_offschema = Counter()

    edge_rels          = Counter()   # supports / tension
    edge_rel_offschema = Counter()

    support_schemes     = Counter()  # scheme on supports edges
    support_scheme_off  = Counter()
    tension_atktypes    = Counter()  # attack_type on tension edges
    tension_atktype_off = Counter()

    nodes_per_conv        = []
    edges_per_conv        = []
    coconstruct_per_conv  = []
    tension_per_conv      = []

    for conv in convs:
        nodes = conv.get("nodes", [])
        edges = conv.get("edges", [])

        nodes_per_conv.append(len(nodes))
        edges_per_conv.append(len(edges))

        for n in nodes:
            ntype, ok = _canonical(n.get("type"), NODE_TYPES)
            (node_types if ok else node_type_offschema)[ntype] += 1

            norigin, ok = _canonical(n.get("origin"), NODE_ORIGINS)
            (node_origins if ok else node_origin_offschema)[norigin] += 1

        cc = sum(1 for n in nodes if n.get("origin") == "co-constructed")
        coconstruct_per_conv.append(cc)

        tension = 0
        for e in edges:
            rel, ok = _canonical(e.get("relation"), EDGE_RELS)
            (edge_rels if ok else edge_rel_offschema)[rel] += 1

            if rel == "supports":
                scheme, sok = _canonical(e.get("scheme"), SUPPORT_SCHEMES)
                (support_schemes if sok else support_scheme_off)[scheme] += 1

            elif rel == "tension":
                tension += 1
                # Prefer explicit `attack_type`; fall back to `scheme` for old data.
                atk = e.get("attack_type") or e.get("scheme")
                atk_val, aok = _canonical(atk, ATTACK_TYPES)
                (tension_atktypes if aok else tension_atktype_off)[atk_val] += 1

        tension_per_conv.append(tension)

    total_nodes  = sum(node_types.values()) + sum(node_type_offschema.values())
    total_edges  = sum(edge_rels.values())  + sum(edge_rel_offschema.values())
    total_supports = edge_rels["supports"]
    total_tension  = edge_rels["tension"]

    return {
        "n_convs":             len(convs),
        "total_nodes":         total_nodes,
        "total_edges":         total_edges,
        "total_supports":      total_supports,
        "total_tension":       total_tension,

        "node_types":          dict(node_types),
        "node_type_offschema": dict(node_type_offschema),
        "node_origins":        dict(node_origins),
        "node_origin_offschema": dict(node_origin_offschema),

        "edge_rels":           dict(edge_rels),
        "edge_rel_offschema":  dict(edge_rel_offschema),

        "support_schemes":     dict(support_schemes),
        "support_scheme_off":  dict(support_scheme_off),
        "tension_atktypes":    dict(tension_atktypes),
        "tension_atktype_off": dict(tension_atktype_off),

        "coconstruct_conv_count": sum(1 for v in coconstruct_per_conv if v > 0),
        "tension_conv_count":     sum(1 for v in tension_per_conv     if v > 0),
        "coconstruct_conv_pct":   100 * sum(1 for v in coconstruct_per_conv if v > 0) / len(convs) if convs else 0,
        "tension_conv_pct":       100 * sum(1 for v in tension_per_conv     if v > 0) / len(convs) if convs else 0,
        "tension_edge_pct":       100 * total_tension / total_edges if total_edges else 0,

        "nodes_per_conv":       np.array(nodes_per_conv),
        "edges_per_conv":       np.array(edges_per_conv),
        "coconstruct_per_conv": np.array(coconstruct_per_conv),
        "tension_per_conv":     np.array(tension_per_conv),
    }


def compute_tree_stats(topic: dict) -> dict:
    tree      = topic.get("tree", {})
    all_nodes = collect_tree_nodes(tree)
    depth_counts = Counter(n.get("depth", 0) for n in all_nodes)
    max_d = tree_max_depth(tree)

    by_depth: dict[int, list[int]] = defaultdict(list)
    for n in all_nodes:
        c = n.get("children", [])
        if c:
            by_depth[n.get("depth", 0)].append(len(c))

    return {
        "max_depth":            max_d,
        "depth_counts":         dict(depth_counts),
        "branch_factor_by_depth": {d: float(np.mean(v)) for d, v in sorted(by_depth.items())},
        "n_leaf_nodes":         sum(1 for n in all_nodes if not n.get("children")),
        "n_internal_nodes":     sum(1 for n in all_nodes if n.get("children")),
    }


# ── text report ───────────────────────────────────────────────────────────────

def print_report(sh: dict, ss: dict, th: dict, ts: dict) -> None:

    def pct_table(ch: dict, cs: dict, total_h: int, total_s: int,
                  title: str, canonical: list[str] | None = None) -> None:
        """Print a two-column percentage table.

        If canonical is given, canonical values appear first (in order),
        then any off-schema values, marked with *.
        """
        all_keys = sorted(set(ch) | set(cs))
        if canonical:
            canon_present = [k for k in canonical if k in set(ch) | set(cs)]
            offschema     = [k for k in all_keys if k not in canonical]
            ordered = canon_present + offschema
        else:
            ordered = all_keys

        print(f"\n  {title}")
        print(f"  {'Category':<24} {'Haiku':>12}  {'Sonnet':>12}")
        print(f"  {'-'*24} {'-'*12}  {'-'*12}")
        for k in ordered:
            h  = ch.get(k, 0)
            s  = cs.get(k, 0)
            hp = 100 * h / total_h if total_h else 0
            sp = 100 * s / total_s if total_s else 0
            tag = " *" if canonical and k not in canonical else "  "
            print(f"  {k:<22}{tag} {h:>5} ({hp:>5.1f}%)   {s:>5} ({sp:>5.1f}%)")
        print(f"  {'TOTAL':<24} {total_h:>5}           {total_s:>5}")
        if canonical:
            off_keys = [k for k in ordered if k not in canonical]
            if off_keys:
                print(f"  (* off-schema: {', '.join(off_keys)})")

    W = 68
    print("\n" + "=" * W)
    print("  BELIEF CONTENT ANALYSIS  —  haiku vs. sonnet  (n=100 each)")
    print("  Schema: beliefs.py SYSTEM_PROMPT")
    print("=" * W)

    # ── nodes ─────────────────────────────────────────────────────────────────
    # merge canonical + off-schema into one counter for display
    merged_nt_h = {**sh["node_types"],   **sh["node_type_offschema"]}
    merged_nt_s = {**ss["node_types"],   **ss["node_type_offschema"]}
    pct_table(merged_nt_h, merged_nt_s,
              sh["total_nodes"], ss["total_nodes"],
              "Node type  (canonical: claim | evidence | constraint | conclusion)",
              canonical=NODE_TYPES)

    merged_no_h = {**sh["node_origins"], **sh["node_origin_offschema"]}
    merged_no_s = {**ss["node_origins"], **ss["node_origin_offschema"]}
    pct_table(merged_no_h, merged_no_s,
              sh["total_nodes"], ss["total_nodes"],
              "Node provenance  (canonical: user | model | co-constructed)",
              canonical=NODE_ORIGINS)

    # ── edges ─────────────────────────────────────────────────────────────────
    merged_er_h = {**sh["edge_rels"], **sh["edge_rel_offschema"]}
    merged_er_s = {**ss["edge_rels"], **ss["edge_rel_offschema"]}
    pct_table(merged_er_h, merged_er_s,
              sh["total_edges"], ss["total_edges"],
              "Edge relation  (canonical: supports | tension)",
              canonical=EDGE_RELS)

    merged_sch_h = {**sh["support_schemes"], **sh["support_scheme_off"]}
    merged_sch_s = {**ss["support_schemes"], **ss["support_scheme_off"]}
    pct_table(merged_sch_h, merged_sch_s,
              sh["total_supports"], ss["total_supports"],
              "supports edges → scheme  (causal|evidential|expert|analogical|consequence|example|other)",
              canonical=SUPPORT_SCHEMES)

    merged_atk_h = {**sh["tension_atktypes"], **sh["tension_atktype_off"]}
    merged_atk_s = {**ss["tension_atktypes"], **ss["tension_atktype_off"]}
    pct_table(merged_atk_h, merged_atk_s,
              sh["total_tension"], ss["total_tension"],
              "tension edges → attack_type  (canonical: rebutting | undercutting)",
              canonical=ATTACK_TYPES)

    # ── key rates ─────────────────────────────────────────────────────────────
    print("\n" + "-" * W)
    print("  KEY RATES")
    print(f"  {'Metric':<47} {'Haiku':>8}  {'Sonnet':>8}")
    print(f"  {'-'*47} {'-'*8}  {'-'*8}")

    def row(label, hv, sv, fmt="{:.1f}"):
        print(f"  {label:<47} {fmt.format(hv):>8}  {fmt.format(sv):>8}")

    row("Convs with ≥1 co-constructed node  (count)",
        sh["coconstruct_conv_count"], ss["coconstruct_conv_count"], fmt="{:.0f}")
    row("Convs with ≥1 co-constructed node  (%)",
        sh["coconstruct_conv_pct"],   ss["coconstruct_conv_pct"])
    row("Convs with ≥1 tension edge  (count)",
        sh["tension_conv_count"],     ss["tension_conv_count"], fmt="{:.0f}")
    row("Convs with ≥1 tension edge  (%)",
        sh["tension_conv_pct"],       ss["tension_conv_pct"])
    row("% of all edges that are tension",
        sh["tension_edge_pct"],       ss["tension_edge_pct"])
    row("Mean nodes per conversation",
        sh["nodes_per_conv"].mean(),  ss["nodes_per_conv"].mean())
    row("Mean edges per conversation",
        sh["edges_per_conv"].mean(),  ss["edges_per_conv"].mean())
    row("Mean co-constructed nodes per conv",
        sh["coconstruct_per_conv"].mean(), ss["coconstruct_per_conv"].mean())
    row("Mean tension edges per conv",
        sh["tension_per_conv"].mean(),     ss["tension_per_conv"].mean())

    # ── cluster tree ──────────────────────────────────────────────────────────
    print("\n" + "-" * W)
    print("  HIERARCHICAL CLUSTER TREE")
    print(f"  {'Metric':<47} {'Haiku':>8}  {'Sonnet':>8}")
    print(f"  {'-'*47} {'-'*8}  {'-'*8}")
    print(f"  {'Max depth':<47} {th['max_depth']:>8}  {ts['max_depth']:>8}")
    print(f"  {'Leaf nodes':<47} {th['n_leaf_nodes']:>8}  {ts['n_leaf_nodes']:>8}")
    print(f"  {'Internal nodes':<47} {th['n_internal_nodes']:>8}  {ts['n_internal_nodes']:>8}")
    print("  Nodes per depth level:")
    for d in sorted(set(th["depth_counts"]) | set(ts["depth_counts"])):
        print(f"    depth {d}: haiku={th['depth_counts'].get(d, 0):>3}  "
              f"sonnet={ts['depth_counts'].get(d, 0):>3}")
    print("  Mean branch factor (internal nodes only):")
    for d in sorted(set(th["branch_factor_by_depth"]) | set(ts["branch_factor_by_depth"])):
        hb = th["branch_factor_by_depth"].get(d, float("nan"))
        sb = ts["branch_factor_by_depth"].get(d, float("nan"))
        print(f"    depth {d}: haiku={hb:>5.1f}  sonnet={sb:>5.1f}")

    # ── statistical tests ─────────────────────────────────────────────────────
    print("\n" + "-" * W)
    print("  MANN-WHITNEY TESTS  (haiku vs sonnet, two-sided)")
    tests = [
        ("nodes per conv",               sh["nodes_per_conv"],        ss["nodes_per_conv"]),
        ("edges per conv",               sh["edges_per_conv"],        ss["edges_per_conv"]),
        ("co-constructed nodes per conv",sh["coconstruct_per_conv"],  ss["coconstruct_per_conv"]),
        ("tension edges per conv",       sh["tension_per_conv"],      ss["tension_per_conv"]),
    ]
    for label, hv, sv in tests:
        u, p = stats.mannwhitneyu(hv, sv, alternative="two-sided")
        stars = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
        print(f"  {label:<45}  U={u:.0f}  p={p:.4f}  {stars}")
    print()


# ── plots ─────────────────────────────────────────────────────────────────────

HC = "#5b9bd5"  # haiku
SC = "#e07b54"  # sonnet


def _bar_pair(ax, ch: dict, cs: dict, total_h: int, total_s: int,
              title: str, canonical: list[str]) -> None:
    # Only plot canonical values — off-schema values are reported in the text table.
    ordered = [k for k in canonical if ch.get(k, 0) or cs.get(k, 0)]
    if not ordered:
        ordered = canonical  # show all slots even if empty

    x = np.arange(len(ordered))
    w = 0.35
    hv = [100 * ch.get(k, 0) / total_h for k in ordered] if total_h else [0] * len(ordered)
    sv = [100 * cs.get(k, 0) / total_s for k in ordered] if total_s else [0] * len(ordered)

    ax.bar(x - w / 2, hv, w, color=HC, label="haiku",  alpha=0.85)
    ax.bar(x + w / 2, sv, w, color=SC, label="sonnet", alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(ordered, rotation=30, ha="right", fontsize=7)
    ax.set_ylabel("% of total", fontsize=7)
    ax.set_title(title, fontsize=8, pad=4)
    ax.tick_params(labelsize=7)
    ax.legend(fontsize=6)


def plot_distributions(sh: dict, ss: dict, th: dict, ts: dict,
                       out_path: Path) -> None:
    fig = plt.figure(figsize=(15, 12))
    fig.suptitle("Belief graph content — haiku vs. sonnet  (schema: beliefs.py)",
                 fontsize=12)
    # Row 0: node type | node provenance | edge relation
    # Row 1: supports scheme | tension attack_type | cc vs tension scatter
    # Row 2: cluster depth (full width)
    gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.60, wspace=0.40)

    ax_nt   = fig.add_subplot(gs[0, 0])
    ax_no   = fig.add_subplot(gs[0, 1])
    ax_er   = fig.add_subplot(gs[0, 2])
    ax_sch  = fig.add_subplot(gs[1, 0])
    ax_atk  = fig.add_subplot(gs[1, 1])
    ax_cc   = fig.add_subplot(gs[1, 2])
    ax_tree = fig.add_subplot(gs[2, :])

    _bar_pair(ax_nt, sh["node_types"], ss["node_types"],
              sh["total_nodes"], ss["total_nodes"],
              "Node type", canonical=NODE_TYPES)

    _bar_pair(ax_no, sh["node_origins"], ss["node_origins"],
              sh["total_nodes"], ss["total_nodes"],
              "Node provenance (origin)", canonical=NODE_ORIGINS)

    _bar_pair(ax_er, sh["edge_rels"], ss["edge_rels"],
              sh["total_edges"], ss["total_edges"],
              "Edge relation", canonical=EDGE_RELS)

    _bar_pair(ax_sch, sh["support_schemes"], ss["support_schemes"],
              sh["total_supports"], ss["total_supports"],
              "supports edges → scheme", canonical=SUPPORT_SCHEMES)

    _bar_pair(ax_atk, sh["tension_atktypes"], ss["tension_atktypes"],
              sh["total_tension"], ss["total_tension"],
              "tension edges → attack_type", canonical=ATTACK_TYPES)

    # Co-constructed vs tension scatter
    ax_cc.scatter(sh["coconstruct_per_conv"], sh["tension_per_conv"],
                  color=HC, alpha=0.5, s=18, label="haiku")
    ax_cc.scatter(ss["coconstruct_per_conv"], ss["tension_per_conv"],
                  color=SC, alpha=0.5, s=18, marker="s", label="sonnet")
    ax_cc.set_xlabel("co-constructed nodes / conv", fontsize=7)
    ax_cc.set_ylabel("tension edges / conv", fontsize=7)
    ax_cc.set_title("Co-constructed vs tension per conv", fontsize=8)
    ax_cc.legend(fontsize=6)
    ax_cc.tick_params(labelsize=7)

    # Cluster depth
    all_depths = sorted(set(th["depth_counts"]) | set(ts["depth_counts"]))
    x = np.arange(len(all_depths))
    w = 0.35
    hd = [th["depth_counts"].get(d, 0) for d in all_depths]
    sd = [ts["depth_counts"].get(d, 0) for d in all_depths]
    ax_tree.bar(x - w / 2, hd, w, color=HC, label="haiku",  alpha=0.85)
    ax_tree.bar(x + w / 2, sd, w, color=SC, label="sonnet", alpha=0.85)
    ax_tree.set_xticks(x)
    ax_tree.set_xticklabels([f"depth {d}" for d in all_depths], fontsize=9)
    ax_tree.set_ylabel("# tree nodes", fontsize=9)
    ax_tree.set_title(
        f"Hierarchical cluster tree — nodes per depth  "
        f"(haiku max={th['max_depth']}, sonnet max={ts['max_depth']})",
        fontsize=9,
    )
    ax_tree.legend(fontsize=8)
    ax_tree.tick_params(labelsize=9)

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"  Saved: {out_path}")


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--haiku",  nargs=2, metavar=("BELIEF", "TOPIC"),
                        default=[
                            "frontend/public/data/donghua-haiku-100/layer_belief_haiku.json",
                            "frontend/public/data/donghua-haiku-100/layer_topic.json",
                        ])
    parser.add_argument("--sonnet", nargs=2, metavar=("BELIEF", "TOPIC"),
                        default=[
                            "processed_teammate/standard_export/layer_belief_sonnet.json",
                            "processed_teammate/standard_export/layer_topic.json",
                        ])
    parser.add_argument("--out-dir", default="analysis_output")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading haiku …")
    convs_h = load_belief(args.haiku[0])
    topic_h = load_topic(args.haiku[1])

    print("Loading sonnet …")
    convs_s = load_belief(args.sonnet[0])
    topic_s = load_topic(args.sonnet[1])

    sh = compute_belief_stats(convs_h)
    ss = compute_belief_stats(convs_s)
    th = compute_tree_stats(topic_h)
    ts = compute_tree_stats(topic_s)

    print_report(sh, ss, th, ts)
    plot_distributions(sh, ss, th, ts, out_dir / "belief_content.png")
    print(f"Done. Plots in {out_dir}/")


if __name__ == "__main__":
    main()
