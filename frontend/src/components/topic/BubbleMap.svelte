<script>
  // @ts-nocheck
  import * as d3 from 'd3';
  import { onMount, onDestroy } from 'svelte';
  import { expandedConvId, bubbleOrigin } from '../../stores.js';

  export let data = [];      // flat conversations array
  export let tree = null;    // hierarchical tree from embed.py (null = legacy fallback)
  export let timeRange = null; // [Date, Date] | null

  const CLUSTER_COLORS = [
    '#4e9af1', '#f0a500', '#6bcb77',
    '#f87171', '#c77dff', '#38bdf8',
    '#fb923c', '#34d399',
  ];
  const UNCLUSTERED_COLOR = '#9ca3af';
  const MARGIN = 44;

  let container;
  let svgEl;
  let width = 1000;
  let height = 600;
  let zoomTransform = d3.zoomIdentity;
  let zoomBehavior = null;

  // ── Search ────────────────────────────────────────────────────────────────
  let searchQuery = '';
  let searchFocused = false;
  let highlightedId = null;

  // ── Lookups ──────────────────────────────────────────────────────────────
  let convByUuid = new Map();     // conv id → conv record
  let nodeMap    = new Map();     // tree node id → tree node (incl. precomputed _cx, _cy)
  let rootNodes  = [];            // root's immediate children (initial bubbles)
  let rootColors = new Map();     // node id → color string (root-level cluster color)

  // Legacy fallback (old flat cluster_id format)
  let clusterMap = new Map();

  // ── Entities driving SVG ─────────────────────────────────────────────────
  let entities = [];
  let expandedSet = new Set();
  let pendingCollapses = [];

  // ── Force simulation ──────────────────────────────────────────────────────
  let simulation;

  // ── Hull rendering ────────────────────────────────────────────────────────
  let hulls = [];

  // ── rAF handle ───────────────────────────────────────────────────────────
  let rafId;

  // ── Interaction state ─────────────────────────────────────────────────────
  let hovered = null;
  let dragging = null;

  // ── Coordinate helpers ────────────────────────────────────────────────────
  let xExtent, yExtent;

  function normX(x) {
    const [lo, hi] = xExtent;
    return hi > lo ? (x - lo) / (hi - lo) : 0.5;
  }
  function normY(y) {
    const [lo, hi] = yExtent;
    return hi > lo ? (y - lo) / (hi - lo) : 0.5;
  }
  function toPx(nx, ny) {
    return { x: MARGIN + nx * (width - MARGIN * 2), y: MARGIN + ny * (height - MARGIN * 2) };
  }
  function convPx(conv) {
    if (conv?.x == null || conv?.y == null) return { x: width / 2, y: height / 2 };
    return toPx(normX(conv.x), normY(conv.y));
  }

  // ── Radius scale ──────────────────────────────────────────────────────────
  function clusterR(size) { return Math.max(60, Math.min(160, Math.sqrt(size) * 32)); }
  const CONV_R = 30;

  // ── Short label ───────────────────────────────────────────────────────────
  function shortLabel(text, maxWords = 4) {
    if (!text) return '';
    const words = text.trim().split(/\s+/);
    return words.length <= maxWords ? text : words.slice(0, maxWords).join(' ') + '…';
  }

  // ── Build lookups ─────────────────────────────────────────────────────────
  function buildLookups() {
    convByUuid.clear();
    nodeMap.clear();
    clusterMap.clear();
    rootNodes = [];
    rootColors.clear();

    // Compute UMAP extents from data with valid coords
    const withCoords = data.filter(d => d.x != null && d.y != null);
    xExtent = d3.extent(withCoords, d => d.x) || [0, 1];
    yExtent = d3.extent(withCoords, d => d.y) || [0, 1];
    if (xExtent[0] === xExtent[1]) xExtent = [xExtent[0] - 1, xExtent[0] + 1];
    if (yExtent[0] === yExtent[1]) yExtent = [yExtent[0] - 1, yExtent[0] + 1];

    for (const conv of data) convByUuid.set(conv.id, conv);

    if (tree) {
      buildNodeMap(tree);
      rootNodes = tree.children || [];
      // Assign a color to each root-level child
      rootNodes.forEach((child, i) => {
        const color = CLUSTER_COLORS[i % CLUSTER_COLORS.length];
        assignColor(child, color);
      });
      // Precompute pixel centroids for all internal nodes
      precomputeCentroids(tree);
    } else {
      // ── Legacy fallback: flat cluster_id ─────────────────────────────────
      let colorIdx = 0;
      for (const conv of data) {
        const cid = conv.cluster_id;
        if (cid == null || cid === -1) continue;
        if (!clusterMap.has(cid)) {
          clusterMap.set(cid, {
            id: cid,
            label: conv.topic_label || `Cluster ${cid}`,
            color: CLUSTER_COLORS[colorIdx++ % CLUSTER_COLORS.length],
            convIds: [],
          });
        }
        clusterMap.get(cid).convIds.push(conv.id);
      }
    }
  }

  function buildNodeMap(node) {
    nodeMap.set(node.id, node);
    if (!node.is_leaf) {
      for (const child of (node.children || [])) buildNodeMap(child);
    }
  }

  function assignColor(node, color) {
    rootColors.set(node.id, color);
    if (!node.is_leaf) {
      for (const child of (node.children || [])) assignColor(child, color);
    }
  }

  function precomputeCentroids(node) {
    if (node.is_leaf) {
      const conv = convByUuid.get(node.id);
      if (conv) {
        const p = convPx(conv);
        node._cx = p.x; node._cy = p.y;
      } else {
        node._cx = width / 2; node._cy = height / 2;
      }
      return;
    }
    // Compute as mean of all descendant leaf UMAP positions
    const leaves = node.leaves || collectLeaves(node);
    let sx = 0, sy = 0, cnt = 0;
    for (const lid of leaves) {
      const conv = convByUuid.get(lid);
      if (conv) {
        const p = convPx(conv);
        sx += p.x; sy += p.y; cnt++;
      }
    }
    node._cx = cnt > 0 ? sx / cnt : width / 2;
    node._cy = cnt > 0 ? sy / cnt : height / 2;
    for (const child of (node.children || [])) precomputeCentroids(child);
  }

  function collectLeaves(node) {
    if (node.is_leaf) return [node.id];
    const out = [];
    for (const c of (node.children || [])) out.push(...collectLeaves(c));
    return out;
  }

  // ── Initialize entities ───────────────────────────────────────────────────
  function initEntities() {
    entities = [];
    expandedSet = new Set();
    pendingCollapses = [];
    const now = performance.now();
    let delay = 0;

    if (tree) {
      // ── Tree mode ──────────────────────────────────────────────────────
      for (const child of rootNodes) {
        const color  = rootColors.get(child.id) || UNCLUSTERED_COLOR;
        const isLeaf = child.is_leaf;
        const baseR  = clusterR(Math.max(child.size, 1));
        const cx     = child._cx ?? width / 2;
        const cy     = child._cy ?? height / 2;
        const conv   = isLeaf ? convByUuid.get(child.id) : null;

        entities.push({
          kind: 'bubble', id: child.id, nodeId: child.id,
          isLeaf,
          depth: 1, baseColor: color, rootColor: color,
          baseR, currentR: 0, x: cx, y: cy, vx: 0, vy: 0,
          name:    isLeaf ? (conv?.short_title || conv?.title || 'Untitled') : (child.short_title || 'Group'),
          summary: isLeaf ? conv?.short_summary : child.short_summary,
          convTitle: isLeaf ? (conv?.title || '') : '',
          size: child.size, parentDotId: null,
          convDate: isLeaf ? conv?.date : null,
          animPhase: 'spawn', animStartR: 0, animTargetR: baseR,
          animStartT: now + delay, animDur: 500,
        });
        delay += 60;
      }
    } else {
      // ── Legacy mode ────────────────────────────────────────────────────
      for (const cluster of clusterMap.values()) {
        const pos   = legacyClusterCentroid(cluster);
        const baseR = clusterR(cluster.convIds.length);
        entities.push({
          kind: 'bubble', id: `cluster-${cluster.id}`, nodeId: null,
          isLeaf: false, depth: 1, baseColor: cluster.color, rootColor: cluster.color,
          baseR, currentR: 0, x: pos.x, y: pos.y, vx: 0, vy: 0,
          name: cluster.label, summary: '', convTitle: '',
          size: cluster.convIds.length, parentDotId: null,
          animPhase: 'spawn', animStartR: 0, animTargetR: baseR,
          animStartT: now + delay, animDur: 500,
        });
        delay += 60;
      }
      for (const conv of data) {
        if ((conv.cluster_id ?? -1) !== -1) continue;
        const pos = convPx(conv);
        entities.push({
          kind: 'bubble', id: conv.id, nodeId: null,
          isLeaf: true, depth: 1, baseColor: UNCLUSTERED_COLOR, rootColor: UNCLUSTERED_COLOR,
          baseR: CONV_R, currentR: 0, x: pos.x, y: pos.y, vx: 0, vy: 0,
          name: conv.short_title || conv.title || 'Untitled',
          summary: conv.short_summary || '',
          convTitle: conv.title || '',
          size: conv.human_turn_count || 1, parentDotId: null,
          convDate: conv.date,
          animPhase: 'spawn', animStartR: 0, animTargetR: CONV_R,
          animStartT: now + delay, animDur: 500,
        });
        delay += 40;
      }
    }
  }

  // ── Legacy centroid (old flat format) ─────────────────────────────────────
  function legacyClusterCentroid(cluster) {
    const convs = cluster.convIds.map(id => convByUuid.get(id)).filter(Boolean);
    if (!convs.length) return toPx(0.5, 0.5);
    return toPx(
      convs.reduce((s, c) => s + normX(c.x), 0) / convs.length,
      convs.reduce((s, c) => s + normY(c.y), 0) / convs.length,
    );
  }

  // ── Rest positions ────────────────────────────────────────────────────────
  function rest(e) {
    if (e.parentDotId) {
      const dot = entities.find(d => d.kind === 'dot' && d.id === e.parentDotId);
      if (dot) return { x: dot.x, y: dot.y };
    }
    if (e.isLeaf) {
      const conv = convByUuid.get(e.id);
      if (conv) return convPx(conv);
    }
    // Internal node: use precomputed centroid
    const treeNode = e.nodeId ? nodeMap.get(e.nodeId) : null;
    if (treeNode?._cx != null) return { x: treeNode._cx, y: treeNode._cy };
    // Legacy fallback
    const cluster = clusterMap.get(e.clusterId);
    if (cluster) return legacyClusterCentroid(cluster);
    return { x: width / 2, y: height / 2 };
  }

  // ── Force simulation ──────────────────────────────────────────────────────
  function startSimulation() {
    if (simulation) simulation.stop();
    simulation = d3.forceSimulation(entities)
      .alphaDecay(0.015).alphaTarget(0).velocityDecay(0.6)
      .force('collide', d3.forceCollide(
        d => Math.max(d.currentR, d.baseR) + (d.kind === 'dot' ? 2 : 6)
      ).strength(1.0).iterations(8))
      .force('x', d3.forceX(d => rest(d).x).strength(d => {
        if (d.frozen) return 0;
        if (d.kind === 'dot' && !d.parentDotId) return 0.12;
        if (d.parentDotId) return 0.10;
        return 0.04;
      }))
      .force('y', d3.forceY(d => rest(d).y).strength(d => {
        if (d.frozen) return 0;
        if (d.kind === 'dot' && !d.parentDotId) return 0.12;
        if (d.parentDotId) return 0.10;
        return 0.04;
      }))
      .force('parentBound', () => {
        for (const e of entities) {
          if (!e.parentDotId || e.frozen || !e._containerR) continue;
          const dot = entities.find(d => d.kind === 'dot' && d.id === e.parentDotId);
          if (!dot) continue;
          const dx = e.x - dot.x, dy = e.y - dot.y;
          const dist = Math.hypot(dx, dy) || 1;
          if (dist > e._containerR) {
            const excess = dist - e._containerR;
            const nx = dx / dist, ny = dy / dist;
            e.vx -= nx * excess * 0.3;
            e.vy -= ny * excess * 0.3;
          }
        }
      })
      .force('dotPull', alpha => {
        for (const e of entities) {
          if (e.frozen || !e.parentDotId) continue;
          const dot = entities.find(d => d.kind === 'dot' && d.id === e.parentDotId);
          if (!dot || dot.frozen) continue;
          const dx = dot.x - e.x, dy = dot.y - e.y;
          const dist = Math.hypot(dx, dy) || 1;
          const desired = e.currentR + dot.currentR + 6;
          const k = 0.18 * alpha;
          e.vx   += (dx / dist) * k * (dist - desired) * 0.55;
          e.vy   += (dy / dist) * k * (dist - desired) * 0.55;
          dot.vx -= (dx / dist) * k * (dist - desired) * 0.08;
          dot.vy -= (dy / dist) * k * (dist - desired) * 0.08;
        }
      })
      .force('friction', () => {
        for (const e of entities) {
          if (e.frozen) continue;
          const f = e.kind === 'dot'
            ? 0.13
            : Math.min(0.96, 0.30 + (e.depth - 1) * 0.22);
          e.vx *= f; e.vy *= f;
        }
      })
      .on('tick', () => { entities = entities; });
  }

  function refreshSim() {
    if (!simulation) return;
    simulation.nodes(entities);
    simulation.alpha(0.6).restart();
  }

  // ── Expand ────────────────────────────────────────────────────────────────
  function expandBubble(bubble) {
    if (bubble.isLeaf || expandedSet.has(bubble.id)) return;

    let children = [];
    if (tree && bubble.nodeId) {
      const treeNode = nodeMap.get(bubble.nodeId);
      if (!treeNode) return;
      children = treeNode.children || [];
    } else {
      // Legacy: conv ids from clusterMap
      const cluster = clusterMap.get(bubble.clusterId);
      if (!cluster) return;
      children = cluster.convIds.map(id => ({
        id, is_leaf: true, size: 1, leaves: [id]
      }));
    }
    if (!children.length) return;

    expandedSet.add(bubble.id);

    bubble.animPhase = 'shrinking-to-dot'; bubble.animStartR = bubble.currentR;
    bubble.animTargetR = 0; bubble.animStartT = performance.now();
    bubble.animDur = 200; bubble.frozen = true;
    bubble.fx = bubble.x; bubble.fy = bubble.y;

    setTimeout(() => {
      const cx = bubble.x, cy = bubble.y;
      const dotR = 7;
      const dot = {
        kind: 'dot', id: bubble.id, nodeId: bubble.nodeId, clusterId: bubble.clusterId,
        parentDotId: null, depth: bubble.depth, baseColor: '#222', baseR: dotR,
        currentR: 0, x: cx, y: cy, vx: 0, vy: 0,
        name: bubble.name, size: bubble.size, isLeaf: false,
        animPhase: 'dot-grow', animStartR: 0, animTargetR: dotR,
        animStartT: performance.now(), animDur: 200,
        frozen: true, fx: cx, fy: cy,
      };
      const idx = entities.findIndex(e => e === bubble);
      if (idx >= 0) entities.splice(idx, 1, dot); else entities.push(dot);
      refreshSim();

      setTimeout(() => {
        const n = children.length;
        const leafR = Math.round(Math.min(bubble.baseR * 0.55, CONV_R + 14));
        const maxChildR = Math.max(...children.map(c =>
          c.is_leaf ? leafR : clusterR(c.size)
        ));
        const ringR = Math.max(maxChildR * 1.8, Math.sqrt(n) * maxChildR * 1.0);
        const emergeDur = 420;
        const stagger = 28;
        const dotEnt = entities.find(e => e.kind === 'dot' && e.id === bubble.id);
        const dx = dotEnt ? dotEnt.x : cx;
        const dy = dotEnt ? dotEnt.y : cy;
        const rootColor = bubble.rootColor || bubble.baseColor;

        children.forEach((child, ki) => {
          const isLeaf = child.is_leaf;
          const conv   = isLeaf ? convByUuid.get(child.id) : null;
          const childBaseR = isLeaf ? leafR : clusterR(child.size);
          const angle = (ki / n) * Math.PI * 2 - Math.PI / 2 + (Math.random() - 0.5) * 0.12;
          const startT = performance.now() + ki * stagger;

          entities.push({
            kind: 'bubble', id: child.id, nodeId: child.id,
            isLeaf,
            clusterId: bubble.clusterId,
            parentDotId: bubble.id,
            depth: bubble.depth + 1,
            baseColor: rootColor, rootColor,
            baseR: childBaseR, currentR: 0, x: dx, y: dy, vx: 0, vy: 0,
            fx: dx, fy: dy, frozen: true,
            name:    isLeaf ? (conv?.short_title || conv?.title || 'Untitled') : (child.short_title || 'Group'),
            summary: isLeaf ? (conv?.short_summary || '') : (child.short_summary || ''),
            convTitle: isLeaf ? (conv?.title || '') : '',
            size: child.size,
            convDate: isLeaf ? conv?.date : null,
            _containerR: ringR + childBaseR + 6,
            animPhase: 'grow', animStartR: 0, animTargetR: childBaseR,
            animStartT: startT, animDur: emergeDur,
            _emergeStartX: dx, _emergeStartY: dy,
            _emergeTargetX: dx + Math.cos(angle) * ringR,
            _emergeTargetY: dy + Math.sin(angle) * ringR,
            _emergeStartT: startT, _emergeDur: emergeDur,
            _unfreezeOnComplete: true,
          });
        });
        refreshSim();

        setTimeout(() => {
          const dotRef = entities.find(e => e.kind === 'dot' && e.id === bubble.id);
          if (dotRef) { dotRef.frozen = false; dotRef.fx = null; dotRef.fy = null; }
          refreshSim();
        }, 500);
      }, 230);
    }, 220);
  }

  // ── Collapse ──────────────────────────────────────────────────────────────
  function collapseDot(dot) {
    const parentId = dot.id;
    if (!expandedSet.has(parentId)) return;
    expandedSet.delete(parentId);

    const kids = entities.filter(e => e.kind === 'bubble' && e.parentDotId === parentId);
    const baseT = performance.now();
    const collapseDur = 380;
    const stagger = 22;
    let lastFinishT = baseT;

    kids.forEach((k, i) => {
      const startT = baseT + (kids.length - 1 - i) * stagger;
      k.animPhase = 'collapse-move-to-dot'; k.animStartR = k.currentR;
      k.animTargetR = 0; k.animStartT = startT; k.animDur = collapseDur;
      k._collapseStartX = k.x; k._collapseStartY = k.y;
      k._collapseTargetX = dot.x; k._collapseTargetY = dot.y;
      k.frozen = true; k.fx = k.x; k.fy = k.y;
      lastFinishT = Math.max(lastFinishT, startT + collapseDur);
    });

    dot.frozen = true; dot.fx = dot.x; dot.fy = dot.y;
    dot.animPhase = 'dot-shrink'; dot.animStartR = dot.currentR;
    dot.animTargetR = 0; dot.animStartT = lastFinishT; dot.animDur = 200;

    const treeNode = dot.nodeId ? nodeMap.get(dot.nodeId) : null;
    const cluster  = dot.clusterId != null ? clusterMap.get(dot.clusterId) : null;

    pendingCollapses.push({
      parentId,
      reappearAt: { x: dot.x, y: dot.y },
      nodeId: dot.nodeId,
      clusterId: dot.clusterId,
      color: dot.baseColor || '#888',
      size: dot.size, name: dot.name,
    });
  }

  function handlePostCollapse() {
    const remaining = [];
    for (const pc of pendingCollapses) {
      const dotAlive  = entities.some(e => e.kind === 'dot'    && e.id === pc.parentId);
      const kidsAlive = entities.some(e => e.kind === 'bubble' && e.parentDotId === pc.parentId);
      if (!dotAlive && !kidsAlive) {
        const treeNode = pc.nodeId ? nodeMap.get(pc.nodeId) : null;
        const isLeaf   = treeNode?.is_leaf ?? false;
        const baseR    = isLeaf ? CONV_R : clusterR(pc.size);
        entities.push({
          kind: 'bubble', id: pc.parentId, nodeId: pc.nodeId, clusterId: pc.clusterId,
          parentDotId: null, depth: 1, baseColor: pc.color, rootColor: pc.color, baseR,
          currentR: 0, x: pc.reappearAt.x, y: pc.reappearAt.y, vx: 0, vy: 0,
          name: pc.name, summary: treeNode?.short_summary || '', convTitle: '', size: pc.size,
          isLeaf,
          animPhase: 'grow', animStartR: 0, animTargetR: baseR,
          animStartT: performance.now(), animDur: 350,
          frozen: true, fx: pc.reappearAt.x, fy: pc.reappearAt.y,
          _unfreezeOnComplete: true,
        });
        refreshSim();
      } else {
        remaining.push(pc);
      }
    }
    pendingCollapses = remaining;
  }

  // ── Animation frame ───────────────────────────────────────────────────────
  function frame(now) {
    for (const e of entities) {
      if (e.animPhase === 'collapse-move-to-dot' && e._collapseTargetX !== undefined) {
        const tt = (now - e.animStartT) / e.animDur;
        if (tt <= 0) {
          e.fx = e._collapseStartX; e.fy = e._collapseStartY;
          e.x = e.fx; e.y = e.fy;
        } else if (tt < 1) {
          const t = d3.easeCubicIn(tt);
          e.fx = e._collapseStartX + (e._collapseTargetX - e._collapseStartX) * t;
          e.fy = e._collapseStartY + (e._collapseTargetY - e._collapseStartY) * t;
          e.x = e.fx; e.y = e.fy;
        }
      }
      if (e._emergeTargetX !== undefined) {
        const tt = (now - e._emergeStartT) / e._emergeDur;
        if (tt < 0) {
          e.fx = e._emergeStartX; e.fy = e._emergeStartY;
          e.x = e.fx; e.y = e.fy;
        } else if (tt < 1) {
          const t = d3.easeCubicOut(tt);
          e.fx = e._emergeStartX + (e._emergeTargetX - e._emergeStartX) * t;
          e.fy = e._emergeStartY + (e._emergeTargetY - e._emergeStartY) * t;
          e.x = e.fx; e.y = e.fy;
        } else {
          e._emergeTargetX = undefined;
        }
      }
      if (e.animDur !== undefined && e.animTargetR !== undefined) {
        const tRaw = (now - e.animStartT) / e.animDur;
        const t = Math.max(0, Math.min(1, tRaw));
        const eased = (e.animPhase === 'collapse-move-to-dot' || e.animPhase === 'dot-shrink')
          ? d3.easeCubicIn(t) : d3.easeCubicOut(t);
        e.currentR = e.animStartR + (e.animTargetR - e.animStartR) * eased;
        if (t >= 1) {
          if (e.animPhase === 'collapse-move-to-dot' || e.animPhase === 'dot-shrink') {
            e._dead = true;
          } else if (e._unfreezeOnComplete) {
            e.frozen = false; e.fx = null; e.fy = null; e._unfreezeOnComplete = false;
          }
          e.animTargetR = undefined; e.animPhase = null;
        }
      }
    }

    if (entities.some(e => e._dead)) {
      entities = entities.filter(e => !e._dead);
      handlePostCollapse();
      refreshSim();
    }

    if (simulation) simulation.tick();
    buildHulls();
    entities = entities;
    rafId = requestAnimationFrame(frame);
  }

  // ── Hull computation ──────────────────────────────────────────────────────
  function buildHulls() {
    hulls = [];
    for (const expandedId of expandedSet) {
      const dot  = entities.find(d => d.kind === 'dot' && d.id === expandedId);
      const kids = entities.filter(e => e.parentDotId === expandedId);
      const members = [...(dot ? [dot] : []), ...kids];
      if (!members.length) continue;
      const pts = [];
      for (const m of members) {
        const r = Math.max(m.currentR, m.baseR * 0.5) + 5;
        for (let i = 0; i < 12; i++) {
          const a = (i / 12) * Math.PI * 2;
          pts.push([m.x + Math.cos(a) * r, m.y + Math.sin(a) * r]);
        }
      }
      if (pts.length < 3) continue;
      const hull = d3.polygonHull(pts);
      if (!hull) continue;
      const line = d3.line().curve(d3.curveBasisClosed);
      const color = entities.find(e => e.id === expandedId)?.rootColor || '#888';
      hulls.push({ path: line(hull), color });
    }
  }

  // ── Text wrapping ─────────────────────────────────────────────────────────
  let measureCtx;
  function wrapText(text, r) {
    if (!measureCtx) {
      const c = document.createElement('canvas');
      measureCtx = c.getContext('2d');
    }
    const maxW = 1.6 * r, maxH = 1.6 * r;
    const words = (text || '').split(/\s+/).filter(Boolean);
    if (!words.length || r < 5) return { lines: [], fontSize: 0 };
    for (let fs = Math.max(4, r * 0.5); fs >= 1; fs *= 0.92) {
      measureCtx.font = `${fs}px system-ui, sans-serif`;
      const lineH = fs * 1.15;
      const lines = [];
      let cur = '';
      for (const w of words) {
        const cand = cur ? cur + ' ' + w : w;
        if (measureCtx.measureText(cand).width <= maxW) cur = cand;
        else { if (cur) lines.push(cur); cur = w; }
      }
      if (cur) lines.push(cur);
      if (lines.length * lineH > maxH) continue;
      if (Math.max(...lines.map(l => measureCtx.measureText(l).width)) > maxW) continue;
      return { lines, fontSize: fs };
    }
    return { lines: [text.slice(0, 10)], fontSize: 1 };
  }

  // ── Conversation search ───────────────────────────────────────────────────
  $: searchResults = searchQuery.trim()
    ? (() => {
        const q = searchQuery.toLowerCase()
        return data
          .map(c => {
            const titleHit   = (c.short_title || c.title || '').toLowerCase().includes(q)
            const summaryHit = (c.short_summary || '').toLowerCase().includes(q)
            const score = (titleHit ? 2 : 0) + (summaryHit ? 1 : 0)
            return { c, score }
          })
          .filter(({ score }) => score > 0)
          .sort((a, b) => b.score - a.score)
          .slice(0, 8)
          .map(({ c }) => c)
      })()
    : []

  function goToResult(conv) {
    const pos = convPx(conv)
    const k = 2.5
    const tx = width / 2 - pos.x * k
    const ty = height / 2 - pos.y * k
    const t = d3.zoomIdentity.translate(tx, ty).scale(k)
    d3.select(svgEl).transition().duration(600).call(zoomBehavior.transform, t)
    highlightedId = conv.id
    searchQuery = ''
    searchFocused = false
    setTimeout(() => { highlightedId = null }, 2500)
  }

  // ── Time filter ───────────────────────────────────────────────────────────
  $: timeStart = timeRange?.[0] ? timeRange[0].getTime() : null;
  $: timeEnd   = timeRange?.[1] ? timeRange[1].getTime() : null;

  function inRange(e) {
    if (timeStart === null) return true;
    if (e.isLeaf && e.convDate) {
      const t = new Date(e.convDate).getTime();
      return !isNaN(t) && t >= timeStart && t <= timeEnd;
    }
    if (!e.isLeaf) {
      const treeNode = e.nodeId ? nodeMap.get(e.nodeId) : null;
      const leaves   = treeNode?.leaves || (e.clusterId != null ? clusterMap.get(e.clusterId)?.convIds : null);
      if (leaves) {
        return leaves.some(lid => {
          const conv = convByUuid.get(lid);
          if (!conv?.date) return false;
          const t = new Date(conv.date).getTime();
          return !isNaN(t) && t >= timeStart && t <= timeEnd;
        });
      }
    }
    return true;
  }

  function displayColor(e) { return inRange(e) ? e.baseColor : '#d1d5db'; }
  function strokeColor(e) {
    if (!inRange(e)) return '#9ca3af';
    try { return d3.color(e.baseColor).darker(0.8).formatHex(); } catch { return '#444'; }
  }

  // ── Click ─────────────────────────────────────────────────────────────────
  function handleClick(ev, e) {
    if (e._wasDragged) { e._wasDragged = false; return; }
    ev.stopPropagation();
    if (e.kind === 'dot') { collapseDot(e); return; }
    if (e.isLeaf) {
      const k = zoomTransform.k || 1;
      bubbleOrigin.set({
        x: e.x * k + (zoomTransform.x || 0),
        y: e.y * k + (zoomTransform.y || 0),
      });
      expandedConvId.set(e.id);
      return;
    }
    if (!expandedSet.has(e.id)) expandBubble(e);
  }

  // ── Drag ──────────────────────────────────────────────────────────────────
  function startDrag(ev, entity) {
    if (ev.button !== 0 || entity.frozen) return;
    ev.stopPropagation();
    entity._wasDragged = false;
    dragging = {
      entity, startMX: ev.clientX, startMY: ev.clientY,
      startEX: entity.x, startEY: entity.y, moved: false,
    };
    entity.fx = entity.x; entity.fy = entity.y;
    simulation?.alphaTarget(0.3).restart();
    window.addEventListener('mousemove', onDragMove);
    window.addEventListener('mouseup', onDragEnd);
  }
  function onDragMove(ev) {
    if (!dragging) return;
    const k = zoomTransform.k || 1;
    dragging.entity.fx = dragging.startEX + (ev.clientX - dragging.startMX) / k;
    dragging.entity.fy = dragging.startEY + (ev.clientY - dragging.startMY) / k;
    if (Math.hypot(ev.clientX - dragging.startMX, ev.clientY - dragging.startMY) > 4)
      dragging.moved = true;
  }
  function onDragEnd() {
    if (!dragging) return;
    dragging.entity.fx = null; dragging.entity.fy = null;
    if (dragging.moved) dragging.entity._wasDragged = true;
    simulation?.alphaTarget(0);
    dragging = null;
    window.removeEventListener('mousemove', onDragMove);
    window.removeEventListener('mouseup', onDragEnd);
  }

  // ── Mount / resize ────────────────────────────────────────────────────────
  function onResize() {
    width  = container?.clientWidth  || window.innerWidth  || 1000;
    height = container?.clientHeight || window.innerHeight - 120 || 600;
    simulation?.alpha(0.4).restart();
  }

  onMount(() => {
    onResize();
    buildLookups();
    initEntities();
    startSimulation();
    rafId = requestAnimationFrame(frame);

    zoomBehavior = d3.zoom()
      .scaleExtent([0.2, 5])
      .filter(ev =>
        ev.type === 'wheel' ||
        (ev.type === 'mousedown' && ev.button === 0) ||
        ev.type.startsWith('touch')
      )
      .on('zoom', ev => { zoomTransform = ev.transform; })
    d3.select(svgEl).call(zoomBehavior);
    window.addEventListener('resize', onResize);
  });

  onDestroy(() => {
    if (rafId) cancelAnimationFrame(rafId);
    simulation?.stop();
    window.removeEventListener('resize', onResize);
    window.removeEventListener('mousemove', onDragMove);
    window.removeEventListener('mouseup', onDragEnd);
  });

  // Legend items — isolates (single-conversation root nodes) are excluded
  $: legendItems = tree
    ? rootNodes
        .filter(n => !n.is_leaf)
        .map(n => ({
          color: rootColors.get(n.id) || UNCLUSTERED_COLOR,
          label: n.short_title || 'Cluster',
        }))
    : [...clusterMap.values()].map(c => ({ color: c.color, label: c.label }));
</script>

<div bind:this={container} class="container">
  <svg bind:this={svgEl} {width} {height}>
    <g transform={zoomTransform.toString()}>
      <!-- Hull fills -->
      {#each hulls as h}
        {#if h.path}
          <path
            d={h.path}
            fill={h.color} fill-opacity="0.10"
            stroke={h.color} stroke-opacity="0.45"
            stroke-width="1.5" stroke-dasharray="2 3"
            pointer-events="none"
          />
        {/if}
      {/each}

      <!-- Dots (collapsed cluster markers) -->
      {#each entities.filter(e => e.kind === 'dot') as e (e.id)}
        <g class="dot"
           on:mousedown={ev => startDrag(ev, e)}
           on:click={ev => handleClick(ev, e)}
           on:mouseenter={() => hovered = e}
           on:mouseleave={() => hovered = null}>
          <circle cx={e.x} cy={e.y} r={Math.max(2, e.currentR)}
                  fill="#222" stroke="white" stroke-width="1.5" />
        </g>
      {/each}

      <!-- Bubbles (clusters + conversations) -->
      {#each entities.filter(e => e.kind === 'bubble') as e (e.id)}
        {@const r = e.currentR}
        {@const dc = displayColor(e)}
        {@const sc = strokeColor(e)}
        {@const wrap = r > 5 ? wrapText(shortLabel(e.name || ''), r) : { lines: [], fontSize: 0 }}
        <g class="bubble"
           on:mousedown={ev => startDrag(ev, e)}
           on:click={ev => handleClick(ev, e)}
           on:mouseenter={() => hovered = e}
           on:mouseleave={() => hovered = null}>
          <circle
            cx={e.x} cy={e.y} r={r}
            fill={dc} fill-opacity={e.isLeaf ? 0.85 : 0.78}
            stroke={sc} stroke-width={e.isLeaf ? 1 : 1.5}
          />
          {#if e.id === highlightedId && r > 2}
            <circle
              cx={e.x} cy={e.y} r={r + 9}
              fill="none" stroke="#6366f1" stroke-width="2.5"
              stroke-dasharray="5 3" pointer-events="none"
              class="highlight-ring"
            />
          {/if}
          {#if wrap.lines.length && wrap.fontSize > 0}
            {#each wrap.lines as line, li}
              <text
                x={e.x}
                y={e.y + (li - (wrap.lines.length - 1) / 2) * wrap.fontSize * 1.15}
                text-anchor="middle" dominant-baseline="middle"
                font-size={wrap.fontSize} fill="white" pointer-events="none"
              >{line}</text>
            {/each}
          {/if}
        </g>
      {/each}
    </g>
  </svg>

  <!-- Search box -->
  <div class="search-box">
    <input
      type="text"
      placeholder="Search conversations…"
      bind:value={searchQuery}
      on:focus={() => { searchFocused = true }}
      on:blur={() => setTimeout(() => { searchFocused = false }, 160)}
      on:keydown={e => {
        if (e.key === 'Escape') { searchQuery = ''; searchFocused = false }
        if (e.key === 'Enter' && searchResults.length > 0) goToResult(searchResults[0])
      }}
    />
    {#if searchFocused && searchResults.length > 0}
      <div class="search-results">
        {#each searchResults as conv}
          <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
          <div class="search-result-item" on:click={() => goToResult(conv)}>
            <span class="sr-title">{conv.short_title || conv.title || 'Untitled'}</span>
            {#if conv.short_summary}
              <span class="sr-summary">{conv.short_summary.length > 72 ? conv.short_summary.slice(0, 72) + '…' : conv.short_summary}</span>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </div>

  <!-- Tooltip -->
  {#if hovered}
    {@const tx = hovered.x * (zoomTransform.k || 1) + (zoomTransform.x || 0) + 14}
    {@const ty = hovered.y * (zoomTransform.k || 1) + (zoomTransform.y || 0) + 8}
    <div class="tooltip" style="left:{tx}px; top:{ty}px">
      {#if hovered.kind === 'dot'}
        <strong>{hovered.name}</strong>
        <span>click to collapse</span>
      {:else if hovered.isLeaf}
        <strong>{hovered.convTitle || hovered.name}</strong>
        {#if hovered.summary}<span class="summary">{hovered.summary}</span>{/if}
        <span>{hovered.convDate ?? ''} · click to explore beliefs</span>
      {:else}
        <strong>{hovered.name}</strong>
        {#if hovered.summary}<span class="summary">{hovered.summary}</span>{/if}
        <span>{hovered.size} {hovered.size === 1 ? 'conversation' : 'conversations'} · click to expand</span>
      {/if}
    </div>
  {/if}

  <!-- Legend -->
  <div class="cluster-legend">
    {#each legendItems as item}
      <div class="legend-item">
        <span class="swatch" style="background:{item.color}"></span>
        <span class="lbl">{item.label}</span>
      </div>
    {/each}
    {#if !tree && data.some(d => (d.cluster_id ?? -1) === -1)}
      <div class="legend-item">
        <span class="swatch" style="background:{UNCLUSTERED_COLOR}"></span>
        <span class="lbl">Unclustered</span>
      </div>
    {/if}
  </div>
</div>

<style>
  .container { position: relative; width: 100%; height: 100%; overflow: hidden; }
  svg {
    display: block;
    background: #fafafa;
    cursor: default;
    user-select: none;
    -webkit-user-select: none;
  }
  .bubble { cursor: pointer; }
  .dot    { cursor: pointer; }
  .tooltip {
    position: fixed;
    background: rgba(0,0,0,0.82);
    color: white;
    padding: 6px 10px;
    border-radius: 5px;
    font-size: 12px;
    pointer-events: none;
    z-index: 100;
    max-width: 300px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .tooltip span { opacity: 0.75; font-size: 11px; }
  .tooltip .summary { opacity: 0.9; font-style: italic; }

  .cluster-legend {
    position: absolute;
    bottom: 16px;
    left: 16px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    background: rgba(255,255,255,0.88);
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    padding: 8px 10px;
    font-size: 11px;
    color: #555;
    pointer-events: none;
    backdrop-filter: blur(4px);
  }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .swatch { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .lbl { line-height: 1.3; }

  /* ── Search ─────────────────────────────────────────────────────────────── */
  .search-box {
    position: absolute;
    top: 12px;
    right: 12px;
    z-index: 30;
    width: 230px;
  }
  .search-box input {
    width: 100%;
    background: rgba(255, 255, 255, 0.94);
    border: 1px solid #d1d5db;
    border-radius: 7px;
    padding: 7px 11px;
    font-size: 0.82rem;
    font-family: inherit;
    color: #111;
    outline: none;
    box-sizing: border-box;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.09);
    backdrop-filter: blur(4px);
    transition: border-color 0.15s;
  }
  .search-box input:focus { border-color: #6366f1; }
  .search-results {
    margin-top: 4px;
    background: rgba(255, 255, 255, 0.97);
    border: 1px solid #e5e7eb;
    border-radius: 7px;
    overflow: hidden;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.13);
    backdrop-filter: blur(4px);
  }
  .search-result-item {
    padding: 8px 11px;
    cursor: pointer;
    display: flex;
    flex-direction: column;
    gap: 2px;
    transition: background 0.1s;
  }
  .search-result-item:hover { background: #f3f4f6; }
  .search-result-item + .search-result-item { border-top: 1px solid #f3f4f6; }
  .sr-title {
    font-size: 0.8rem;
    font-weight: 600;
    color: #111;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .sr-summary {
    font-size: 0.71rem;
    color: #6b7280;
    line-height: 1.35;
  }

  /* ── Highlight ring animation ────────────────────────────────────────────── */
  .highlight-ring {
    animation: ring-pulse 0.7s ease-in-out infinite alternate;
  }
  @keyframes ring-pulse {
    from { opacity: 0.9; }
    to   { opacity: 0.25; }
  }
</style>
