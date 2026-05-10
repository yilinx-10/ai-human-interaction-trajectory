<script>
  // @ts-nocheck  — D3 generics and dynamic window properties; type safety via logic, not annotations
  import { onMount, onDestroy, afterUpdate } from 'svelte'
  import { get } from 'svelte/store'
  import {
    forceSimulation, forceLink, forceManyBody,
    forceCenter, forceCollide, forceX, forceY,
  } from 'd3-force'
  import { select } from 'd3-selection'
  import { drag } from 'd3-drag'
  import { zoom, zoomIdentity } from 'd3-zoom'
  import { polygonHull } from 'd3-polygon'
  import {
    selectedItem,
    beliefViewMode, beliefFocusedConvId,
    beliefEdits, beliefEditMode,
  } from '../../stores.js'
  import { convNodeSet, recommendLinks } from '../../lib/beliefUtils.js'

  export let nodes = []
  export let edges = []
  export let perConversation = []
  export let idToCanon = new Map()

  const NODE_COLOR   = { claim: '#4e9af1', evidence: '#f0a500', conclusion: '#6bcb77', constraint: '#fb923c', other: '#94a3b8' }
  const ORIGIN_COLOR = { user: '#2dd4bf', model: '#f87171', 'co-constructed': '#a78bfa' }

  function nodeFill(d) { return ORIGIN_COLOR[d.origin] ?? NODE_COLOR[d.type] ?? '#888' }
  const EDGE_COLOR = { supports: '#6bcb77', contradicts: '#f87171', elaborates: '#8fa8c8', causes: '#f0a500', alternatives: '#a78bfa' }
  const CONV_PALETTE = [
    { fill: 'rgba(78,154,241,0.08)',  stroke: 'rgba(78,154,241,0.35)'  },
    { fill: 'rgba(240,165,0,0.08)',   stroke: 'rgba(240,165,0,0.35)'   },
    { fill: 'rgba(107,203,119,0.08)', stroke: 'rgba(107,203,119,0.35)' },
    { fill: 'rgba(248,113,113,0.08)', stroke: 'rgba(248,113,113,0.35)' },
    { fill: 'rgba(199,125,255,0.08)', stroke: 'rgba(199,125,255,0.35)' },
    { fill: 'rgba(56,189,248,0.08)',  stroke: 'rgba(56,189,248,0.35)'  },
    { fill: 'rgba(251,146,60,0.08)',  stroke: 'rgba(251,146,60,0.35)'  },
  ]

  let svgEl
  let simulation
  let currentTransform = zoomIdentity
  const posCache = new Map()  // nodeId → {x, y}

  // Overlay UI state (component-local, triggers Svelte re-render via assignments)
  let addNodeScreenPos = null  // { x, y } viewport coords
  let addNodeGraphPos  = null  // { x, y } graph coords
  let addNodeForm = { text: '', type: 'claim' }
  let edgePicker  = null      // { screenX, screenY, src, tgt }
  let edgeSource     = null   // nodeId of first click in addEdge mode
  let relationType   = 'supports'
  let recommendations = []   // suggested cross-network targets while edgeSource is set

  // Reactive mirrors of stores (readable in D3 callbacks as closure vars)
  $: viewMode      = $beliefViewMode
  $: focusedConvId = $beliefFocusedConvId
  $: editMode      = $beliefEditMode

  // Cross-network link suggestions: work in both global and conversation modes.
  // Use full node list so cross-network targets appear even when zoomed into one conv.
  $: recommendations = edgeSource
    ? recommendLinks(edgeSource, nodes, visibleEdges)
    : []

  // ── Visible node/edge computation ────────────────────────────────────────────

  $: convIds = (viewMode === 'conversation' && focusedConvId)
    ? convNodeSet(focusedConvId, perConversation, idToCanon)
    : null

  $: visibleNodes = (() => {
    const del = $beliefEdits.deletedNodes
    let base
    if (convIds !== null) {
      // Start with this conversation's canonical nodes
      const extended = new Set(convIds)
      // Pull in any nodes connected to this conv via existing or added edges
      for (const e of edges) {
        const s = typeof e.source === 'object' ? e.source.id : e.source
        const t = typeof e.target === 'object' ? e.target.id : e.target
        if (convIds.has(s) && !del.has(t)) extended.add(t)
        if (convIds.has(t) && !del.has(s)) extended.add(s)
      }
      for (const ae of $beliefEdits.edges) {
        if (convIds.has(ae.source)) extended.add(ae.target)
        if (convIds.has(ae.target)) extended.add(ae.source)
      }
      base = nodes.filter(n => !del.has(n.id) && extended.has(n.id))
    } else {
      base = nodes.filter(n => !del.has(n.id))
    }
    const added = $beliefEdits.nodes.filter(n =>
      !del.has(n.id) &&
      (viewMode === 'global' || n.convId === focusedConvId)
    )
    return [...base, ...added]
  })()

  $: visibleEdges = (() => {
    const del     = $beliefEdits.deletedEdges
    const nodeSet = new Set(visibleNodes.map(n => n.id))
    const edgeKey = e => {
      const s = typeof e.source === 'object' ? e.source.id : e.source
      const t = typeof e.target === 'object' ? e.target.id : e.target
      return `${s}→${t}:${e.relation}`
    }
    const base = edges.filter(e => {
      if (del.has(edgeKey(e))) return false
      const s = typeof e.source === 'object' ? e.source.id : e.source
      const t = typeof e.target === 'object' ? e.target.id : e.target
      return nodeSet.has(s) && nodeSet.has(t)
    })
    const added = $beliefEdits.edges.filter(e => {
      const key = `${e.source}→${e.target}:${e.relation}`
      return !del.has(key) && nodeSet.has(e.source) && nodeSet.has(e.target)
    })
    return [...base, ...added]
  })()

  // ── Helpers ───────────────────────────────────────────────────────────────────

  function nodeRadius(d) { return 6 + ((d.frequency ?? 1) - 1) * 2.5 }

  function expandHull(hull, padding = 32) {
    const cx = hull.reduce((s, p) => s + p[0], 0) / hull.length
    const cy = hull.reduce((s, p) => s + p[1], 0) / hull.length
    return hull.map(([x, y]) => {
      const dx = x - cx, dy = y - cy
      const len = Math.sqrt(dx * dx + dy * dy) || 1
      return [x + (dx / len) * padding, y + (dy / len) * padding]
    })
  }

  function computeHulls(simNodes) {
    const idToPos = new Map(simNodes.map(n => [n.id, [n.x, n.y]]))
    return perConversation.map((conv, i) => {
      const cids = convNodeSet(conv.id, perConversation, idToCanon)
      const pts  = [...cids].map(id => idToPos.get(id)).filter(Boolean)
      if (!pts.length) return null
      const color = CONV_PALETTE[i % CONV_PALETTE.length]
      if (pts.length === 1) {
        return { type: 'circle', conv, color, cx: pts[0][0], cy: pts[0][1], r: 34 }
      }
      // Build hull from expanded point cloud around each node
      const cloud = pts.flatMap(([x, y]) => [
        [x - 18, y - 18], [x + 18, y - 18],
        [x - 18, y + 18], [x + 18, y + 18],
      ])
      // @ts-ignore – polygonHull expects [number,number][] but JS cannot assert tuple type
      const raw = polygonHull(cloud)
      if (!raw) return null
      return { type: 'hull', conv, color, points: expandHull(raw, 14) }
    }).filter(Boolean)
  }

  function hullD(pts) {
    return 'M' + pts.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join('L') + 'Z'
  }

  // Quadratic-bezier sine-wave path for contradictory edges.
  // The final segment is always a straight line so orient="auto" gives the correct
  // arrowhead direction. The path stops `stopBefore` px before the target centre
  // (≈ node surface) so the arrowhead lands at the node boundary.
  function wavyPath(x1, y1, x2, y2, stopBefore = 11) {
    const dx = x2 - x1, dy = y2 - y1
    const len = Math.sqrt(dx * dx + dy * dy)
    if (len < 2) return `M${x1.toFixed(1)},${y1.toFixed(1)}L${x2.toFixed(1)},${y2.toFixed(1)}`
    const ux = dx / len, uy = dy / len        // unit vector toward target
    const nx = -uy,     ny = ux               // perpendicular unit vector
    // Target for the wavy portion: stop a bit before the node centre
    const tx = x2 - ux * stopBefore, ty = y2 - uy * stopBefore
    const wdx = tx - x1, wdy = ty - y1
    const segs = Math.max(2, Math.round(len / 28))
    const amp  = 7
    let d = `M${x1.toFixed(1)},${y1.toFixed(1)}`
    for (let i = 0; i < segs - 1; i++) {
      const t1 = (i + 0.5) / segs, t2 = (i + 1) / segs
      const sign = i % 2 === 0 ? 1 : -1
      const cx = x1 + wdx * t1 + nx * amp * sign
      const cy = y1 + wdy * t1 + ny * amp * sign
      const ex = (x1 + wdx * t2).toFixed(1)
      const ey = (y1 + wdy * t2).toFixed(1)
      d += ` Q${cx.toFixed(1)},${cy.toFixed(1)} ${ex},${ey}`
    }
    // Straight final segment → correct arrowhead orientation
    d += ` L${tx.toFixed(1)},${ty.toFixed(1)}`
    return d
  }

  // ── Mount / D3 setup ──────────────────────────────────────────────────────────

  onMount(() => {
    const svgSel = select(svgEl)
    const W = svgEl.clientWidth  || 900
    const H = svgEl.clientHeight || 600

    // Arrow markers
    const defs = svgSel.append('defs')
    const mkArrow = (id, color) => {
      defs.append('marker')
        .attr('id', id).attr('viewBox', '0 -4 8 8')
        .attr('refX', 24).attr('refY', 0)
        .attr('markerWidth', 5).attr('markerHeight', 5)
        .attr('orient', 'auto')
        .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', color)
    }
    mkArrow('arrow-supports', '#6bcb77')
    mkArrow('arrow-causes',   '#f0a500')
    // Separate marker for wavy edges: refX=0 so the tip lands exactly at the
    // path endpoint (which wavyPath already stops at the node surface).
    defs.append('marker')
      .attr('id', 'arrow-wavy').attr('viewBox', '0 -4 8 8')
      .attr('refX', 0).attr('refY', 0)
      .attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', '#f87171')

    // Zoom behaviour
    const zoomBehavior = zoom()
      .scaleExtent([0.1, 4])
      .on('zoom', e => { currentTransform = e.transform; g.attr('transform', e.transform) })
    svgSel.call(zoomBehavior)

    // Double-click on SVG background → place new node
    svgSel.on('dblclick.addnode', function(event) {
      if (get(beliefEditMode) !== 'addNode') return
      event.stopPropagation()
      const rect = svgEl.getBoundingClientRect()
      const [gx, gy] = currentTransform.invert([event.clientX - rect.left, event.clientY - rect.top])
      addNodeScreenPos = { x: event.clientX, y: event.clientY }
      addNodeGraphPos  = { x: gx, y: gy }
      addNodeForm = { text: '', type: 'claim' }
    })

    const g         = svgSel.append('g').attr('class', 'graph-root')
    const hullGroup = g.append('g').attr('class', 'hulls')
    const linkGroup = g.append('g').attr('class', 'links')
    const nodeGroup = g.append('g').attr('class', 'nodes')

    // ── Core render function (re-called on data changes) ──────────────────────
    let prevRenderMode = null   // tracks mode across render calls for transition animation

    function render() {
      const curMode = get(beliefViewMode)
      const modeJustChanged = prevRenderMode !== null && prevRenderMode !== curMode
      prevRenderMode = curMode
      const simNodes = visibleNodes.map(n => ({
        ...n,
        x: posCache.get(n.id)?.x ?? (W / 2 + (Math.random() - 0.5) * 200),
        y: posCache.get(n.id)?.y ?? (H / 2 + (Math.random() - 0.5) * 200),
      }))
      const nodeSet = new Set(simNodes.map(n => n.id))
      const simLinks = visibleEdges
        .map(e => ({
          ...e,
          source: typeof e.source === 'object' ? e.source.id : e.source,
          target: typeof e.target === 'object' ? e.target.id : e.target,
        }))
        .filter(e => nodeSet.has(e.source) && nodeSet.has(e.target))

      if (simulation) simulation.stop()
      hullGroup.selectAll('*').remove()
      linkGroup.selectAll('*').remove()
      nodeGroup.selectAll('*').remove()

      // ── Links ────────────────────────────────────────────────────────────────
      const edgeDeleteHandler = (event, d) => {
        if (get(beliefEditMode) !== 'delete') return
        event.stopPropagation()
        const s = typeof d.source === 'object' ? d.source.id : d.source
        const t = typeof d.target === 'object' ? d.target.id : d.target
        beliefEdits.update(ed => ({
          ...ed,
          deletedEdges: new Set([...ed.deletedEdges, `${s}→${t}:${d.relation}`]),
        }))
      }

      const straightLinks = simLinks.filter(e => e.relation !== 'contradicts')
      const wavyLinks     = simLinks.filter(e => e.relation === 'contradicts')

      const linkLine = linkGroup.selectAll('.link-line').data(straightLinks).join('line')
        .attr('class', d => `link link-line link-${d.relation}`)
        .attr('stroke', d => EDGE_COLOR[d.relation] ?? '#555')
        .attr('stroke-width', 1.5)
        .attr('stroke-dasharray', d => d.relation === 'elaborates' ? '5,3' : d.relation === 'alternatives' ? '2,4' : null)
        .attr('marker-end', d => d.relation === 'supports' ? 'url(#arrow-supports)' : d.relation === 'causes' ? 'url(#arrow-causes)' : null)
        .attr('opacity', 0.65)
        .on('click', edgeDeleteHandler)

      const linkWavy = linkGroup.selectAll('.link-wavy').data(wavyLinks).join('path')
        .attr('class', 'link link-wavy link-contradicts')
        .attr('stroke', EDGE_COLOR.contradicts)
        .attr('stroke-width', 2)
        .attr('fill', 'none')
        .attr('marker-end', 'url(#arrow-wavy)')
        .attr('opacity', 0.72)
        .on('click', edgeDeleteHandler)

      // ── Nodes ────────────────────────────────────────────────────────────────
      const node = nodeGroup.selectAll('.node-g').data(simNodes, d => d.id).join('g')
        .attr('class', 'node-g')
        .style('cursor', 'pointer')
        .call(
          drag()
            .on('start', (event, d) => {
              if (!event.active) simulation.alphaTarget(0.3).restart()
              d.fx = d.x; d.fy = d.y
            })
            .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
            .on('end',  (event, d) => {
              if (!event.active) simulation.alphaTarget(0)
              d.fx = null; d.fy = null
            })
        )
        .on('click', (event, d) => {
          event.stopPropagation()
          const mode = get(beliefEditMode)

          if (mode === 'delete') {
            beliefEdits.update(ed => ({
              ...ed,
              deletedNodes: new Set([...ed.deletedNodes, d.id]),
            }))
            return
          }

          if (mode === 'addEdge') {
            if (edgeSource === d.id) {
              // Click same node again → cancel selection
              edgeSource = null
              node.select('.node-shape').attr('stroke', '#3a4060').attr('stroke-width', 1.5)
            } else {
              // Click any other node (with or without prior selection) → set as new source
              edgeSource = d.id
              node.select('.node-shape')
                .attr('stroke', n => n.id === d.id ? '#6366f1' : '#3a4060')
                .attr('stroke-width', n => n.id === d.id ? 3 : 1.5)
            }
            return
          }

          // Toggle-deselect: second click on the same node closes the side panel
          const curSel = get(selectedItem)
          if (curSel?.type === 'belief' && curSel?.data?.id === d.id) {
            selectedItem.set(null)
            return
          }

          // Default click: in global mode, zoom into this node's first conversation
          if (get(beliefViewMode) === 'global') {
            const convId = d.conversations?.[0]?.id
            if (convId) {
              beliefFocusedConvId.set(convId)
              beliefViewMode.set('conversation')
            }
          }
          selectedItem.set({ type: 'belief', data: d })
        })
        .on('dblclick', (event, d) => {
          event.stopPropagation()
          const current = get(beliefEdits).texts.get(d.id) ?? d.text
          const newText = prompt('Edit belief text:', current)
          if (newText !== null && newText.trim() && newText.trim() !== current) {
            beliefEdits.update(ed => {
              const texts = new Map(ed.texts)
              texts.set(d.id, newText.trim())
              return { ...ed, texts }
            })
          }
        })

      // ── Node shapes ──────────────────────────────────────────────────────────
      if (viewMode === 'conversation') {
        // CONVERSATION MODE: text-inside pill nodes sized to fit their label
        node.each(function(d) {
          const g = select(this)
          const edited = get(beliefEdits).texts.get(d.id)
          const label = edited ?? d.text_short ?? (d.text ?? '').slice(0, 26)
          const w = Math.max(80, label.length * 6.2 + 28)
          const h = 28
          d._w = w; d._h = h   // store for collision + selection ring sizing
          g.append('rect')
            .attr('class', 'node-shape')
            .attr('x', -w / 2).attr('y', -h / 2)
            .attr('width', w).attr('height', h)
            .attr('rx', 14)
            .attr('fill', nodeFill(d))
            .attr('stroke', d.shared ? '#6366f1' : '#3a4060')
            .attr('stroke-width', d.shared ? 2 : 1.5)
            .attr('stroke-dasharray', d.shared ? '4,2' : null)
            .attr('opacity', 0.9)
          g.append('text')
            .attr('dy', '0.35em')
            .attr('text-anchor', 'middle')
            .attr('font-size', '10px')
            .attr('font-weight', '500')
            .attr('fill', '#fff')
            .attr('pointer-events', 'none')
            .text(label)
        })
        // Shared badge at pill top-right
        node.filter(d => d.shared)
          .append('circle')
          .attr('r', 4)
          .attr('cx', d => (d._w ?? 80) / 2 - 5)
          .attr('cy', d => -(d._h ?? 28) / 2 + 5)
          .attr('fill', '#6366f1')
          .attr('stroke', '#3a4060')
          .attr('stroke-width', 1)
          .attr('pointer-events', 'none')
          .append('title').text('Shared across multiple conversations')
      } else {
        // GLOBAL MODE: small type-shaped nodes with label below
        node.filter(d => d.type === 'claim')
          .append('rect')
          .attr('class', 'node-shape')
          .attr('x', d => -nodeRadius(d))
          .attr('y', d => -nodeRadius(d) * 0.65)
          .attr('width',  d => nodeRadius(d) * 2)
          .attr('height', d => nodeRadius(d) * 1.3)
          .attr('rx', 3)
          .attr('fill', d => nodeFill(d))
          .attr('stroke', '#3a4060')
          .attr('stroke-width', d => d.shared ? 2.5 : 1.5)
          .attr('stroke-dasharray', d => d.shared ? '4,2' : null)
          .attr('opacity', 0.9)

        node.filter(d => d.type === 'evidence' || d.type === 'assumption')
          .append('polygon')
          .attr('class', 'node-shape')
          .attr('points', d => {
            const r = nodeRadius(d)
            return `0,${-r} ${r * 1.15},0 0,${r} ${-r * 1.15},0`
          })
          .attr('fill', d => nodeFill(d))
          .attr('stroke', '#3a4060')
          .attr('stroke-width', d => d.shared ? 2.5 : 1.5)
          .attr('stroke-dasharray', d => d.shared ? '4,2' : null)
          .attr('opacity', 0.9)

        node.filter(d => d.type === 'other')
          .append('circle')
          .attr('class', 'node-shape')
          .attr('r', d => nodeRadius(d) * 0.8)
          .attr('fill', d => nodeFill(d))
          .attr('stroke', '#3a4060')
          .attr('stroke-width', d => d.shared ? 2.5 : 1.5)
          .attr('stroke-dasharray', '3,2')
          .attr('opacity', 0.7)

        node.filter(d => d.type === 'constraint')
          .append('polygon')
          .attr('class', 'node-shape')
          .attr('points', d => {
            const r = nodeRadius(d)
            return `${-r},${-r * 0.6} ${r},${-r * 0.6} 0,${r}`
          })
          .attr('fill', d => nodeFill(d))
          .attr('stroke', '#3a4060')
          .attr('stroke-width', d => d.shared ? 2.5 : 1.5)
          .attr('stroke-dasharray', d => d.shared ? '4,2' : null)
          .attr('opacity', 0.9)

        node.filter(d => d.type === 'conclusion')
          .append('circle')
          .attr('class', 'node-shape')
          .attr('r', d => nodeRadius(d))
          .attr('fill', d => nodeFill(d))
          .attr('stroke', '#3a4060')
          .attr('stroke-width', d => d.shared ? 2.5 : 1.5)
          .attr('stroke-dasharray', d => d.shared ? '4,2' : null)
          .attr('opacity', 0.9)

        // Shared badge
        node.filter(d => d.shared)
          .append('circle')
          .attr('r', 3.5)
          .attr('cx', d =>  nodeRadius(d) * 0.65)
          .attr('cy', d => -nodeRadius(d) * 0.65)
          .attr('fill', '#6366f1')
          .attr('stroke', '#3a4060')
          .attr('stroke-width', 1)
          .attr('pointer-events', 'none')
          .append('title').text('Shared across multiple conversations')

        // Label below node
        node.append('text')
          .attr('dy', d => nodeRadius(d) + 11)
          .attr('text-anchor', 'middle')
          .attr('font-size', '9px')
          .attr('fill', '#7c85a2')
          .attr('pointer-events', 'none')
          .text(d => {
            const edited = get(beliefEdits).texts.get(d.id)
            const t = edited ?? d.text_short ?? d.text ?? ''
            return t.length > 30 ? t.slice(0, 30) + '…' : t
          })
      }

      // ── Selection ring (white ring around currently selected belief node) ────
      const selId = get(selectedItem)?.type === 'belief' ? get(selectedItem)?.data?.id : null
      if (selId) {
        node.filter(d => d.id === selId)
          .append('circle')
          .attr('class', 'sel-ring')
          .attr('r', d => viewMode === 'conversation'
            ? (d._w ?? 80) / 2 + 6
            : nodeRadius(d) + 7)
          .attr('fill', 'none')
          .attr('stroke', '#6366f1')
          .attr('stroke-width', 2.5)
          .attr('opacity', 0.9)
          .attr('pointer-events', 'none')
      }

      // ── Recommendation highlighting ──────────────────────────────────────────
      // When a source node is selected in global addEdge mode, dim everything
      // except the source and the recommended targets; add a glow ring to targets.
      if (edgeSource && viewMode === 'global') {
        const recIds = new Set(recommendations.map(r => r.id))
        node.select('.node-shape')
          .attr('opacity', d => (d.id === edgeSource || recIds.has(d.id)) ? 1.0 : 0.18)
        node.select('text')
          .attr('opacity', d => (d.id === edgeSource || recIds.has(d.id)) ? 1.0 : 0.12)
        // Pulsing ring around recommended nodes
        node.filter(d => recIds.has(d.id))
          .append('circle')
          .attr('class', 'rec-ring')
          .attr('r', d => nodeRadius(d) + 6)
          .attr('fill', 'none')
          .attr('stroke', '#6366f1')
          .attr('stroke-width', 2)
          .attr('opacity', 0.75)
          .attr('pointer-events', 'none')
        // Highlight ring on source node
        node.filter(d => d.id === edgeSource)
          .append('circle')
          .attr('class', 'src-ring')
          .attr('r', d => nodeRadius(d) + 6)
          .attr('fill', 'none')
          .attr('stroke', '#6366f1')
          .attr('stroke-width', 2.5)
          .attr('opacity', 0.9)
          .attr('pointer-events', 'none')
      }

      // ── Simulation ───────────────────────────────────────────────────────────
      const convMode = viewMode === 'conversation'
      simulation = forceSimulation(simNodes)
        .force('link',    forceLink(simLinks).id(d => d.id).distance(convMode ? 180 : 100))
        .force('charge',  forceManyBody().strength(convMode ? -700 : -280))
        .force('center',  forceCenter(W / 2, H / 2))
        .force('collide', forceCollide().radius(d =>
          convMode ? (d._w ?? 80) / 2 + 10 : nodeRadius(d) + 10))
        .force('x', forceX(W / 2).strength(0.03))
        .force('y', forceY(H / 2).strength(0.03))
        .on('tick', () => {
          simNodes.forEach(n => posCache.set(n.id, { x: n.x, y: n.y }))

          linkLine
            .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
          linkWavy
            .attr('d', d => wavyPath(d.source.x, d.source.y, d.target.x, d.target.y))
          node.attr('transform', d => `translate(${d.x},${d.y})`)

          // ── Hull update (global mode only) ────────────────────────────────
          if (get(beliefViewMode) !== 'global') {
            hullGroup.selectAll('*').remove()
            return
          }

          const hulls = computeHulls(simNodes)
          const hullUpd = hullGroup.selectAll('.hull-g').data(hulls, d => d.conv.id)

          const entered = hullUpd.enter().append('g').attr('class', 'hull-g')
          entered.append('path').attr('class', 'hull-shape')
            .attr('stroke-width', 1.5)
            .attr('stroke-dasharray', '6,4')
            .style('cursor', 'pointer')
            .on('click', (event, d) => {
              event.stopPropagation()
              beliefFocusedConvId.set(d.conv.id)
              beliefViewMode.set('conversation')
            })
            .on('mouseover', function() { select(this).attr('stroke-width', 2.5) })
            .on('mouseout',  function() { select(this).attr('stroke-width', 1.5) })
          entered.append('text').attr('class', 'hull-label')
            .attr('text-anchor', 'middle')
            .attr('font-size', '9.5px')
            .attr('fill', '#7c85a2')
            .attr('pointer-events', 'none')

          hullUpd.exit().remove()

          hullGroup.selectAll('.hull-g').data(hulls, d => d.conv.id)
            .each(function(d) {
              const g = select(this)
              // Shape
              g.select('.hull-shape')
                .attr('fill', d.color.fill)
                .attr('stroke', d.color.stroke)
                .attr('opacity', 0.75)
                .each(function(d) {
                  if (d.type === 'circle') {
                    select(this).attr('d',
                      `M ${d.cx} ${d.cy} m -${d.r},0 ` +
                      `a ${d.r},${d.r} 0 1,0 ${d.r*2},0 ` +
                      `a ${d.r},${d.r} 0 1,0 -${d.r*2},0`
                    )
                  } else {
                    select(this).attr('d', hullD(d.points))
                  }
                })
              // Label above hull
              const labelX = d.type === 'circle'
                ? d.cx
                : d.points.reduce((s, p) => s + p[0], 0) / d.points.length
              const labelY = d.type === 'circle'
                ? d.cy - d.r - 8
                : Math.min(...d.points.map(p => p[1])) - 8
              const title = d.conv.title
              g.select('.hull-label')
                .attr('x', labelX).attr('y', labelY)
                .text(title.length > 24 ? title.slice(0, 24) + '…' : title)
            })
        })

      // ── Mode transition fade-in ───────────────────────────────────────────
      if (modeJustChanged) {
        nodeGroup.style('opacity', '0')
        linkGroup.style('opacity', '0')
        hullGroup.style('opacity', '0')
        requestAnimationFrame(() => {
          nodeGroup.style('transition', 'opacity 0.38s ease').style('opacity', '')
          linkGroup.style('transition', 'opacity 0.38s ease').style('opacity', '')
          hullGroup.style('transition', 'opacity 0.38s ease').style('opacity', '')
          setTimeout(() => {
            nodeGroup.style('transition', '')
            linkGroup.style('transition', '')
            hullGroup.style('transition', '')
          }, 420)
        })
      }

      window.__graphRender = render
    }

    render()
  })

  // ── Reactive re-render when visible set or mode changes ───────────────────────
  let prevKey = ''
  afterUpdate(() => {
    const selId = $selectedItem?.type === 'belief' ? $selectedItem.data?.id : ''
    const key = [
      visibleNodes.map(n => n.id).join(','),
      visibleEdges.length,
      viewMode,
      focusedConvId,
      editMode,
      edgeSource,
      $beliefEdits.texts.size,
      selId,
    ].join('|')
    if (key !== prevKey) {
      prevKey = key
      window.__graphRender?.()
    }
  })

  onDestroy(() => {
    simulation?.stop()
    delete window.__graphRender
  })

  // ── Overlay actions ───────────────────────────────────────────────────────────

  function confirmAddNode() {
    if (!addNodeForm.text.trim() || !addNodeGraphPos) return
    const id = `user_${Date.now()}`
    const convId = get(beliefFocusedConvId)
    beliefEdits.update(ed => ({
      ...ed,
      nodes: [...ed.nodes, {
        id,
        text:          addNodeForm.text.trim(),
        type:          addNodeForm.type,
        convId,
        conversations: convId ? [{ id: convId, title: '', date: '' }] : [],
        frequency:     1,
        shared:        false,
        firstDate:     new Date().toISOString().slice(0, 10),
        _userAdded:    true,
      }],
    }))
    posCache.set(id, addNodeGraphPos)
    addNodeScreenPos = null
    addNodeGraphPos  = null
  }

  function confirmAddEdge() {
    if (!edgePicker) return
    beliefEdits.update(ed => ({
      ...ed,
      edges: [...ed.edges, { source: edgePicker.src, target: edgePicker.tgt, relation: relationType }],
    }))
    edgePicker   = null
    relationType = 'parallel'
  }

  function cancelOverlay() {
    addNodeScreenPos = null
    addNodeGraphPos  = null
    edgePicker       = null
    edgeSource       = null
    relationType     = 'supports'
  }

  // Called when the user clicks a recommendation card instead of the graph node
  function selectRecommendation(targetNode) {
    if (!edgeSource) return
    const pos = posCache.get(targetNode.id) ?? { x: svgEl.clientWidth / 2, y: svgEl.clientHeight / 2 }
    const rect = svgEl.getBoundingClientRect()
    const [sx, sy] = currentTransform.apply([pos.x, pos.y])
    edgePicker = {
      screenX: Math.min(rect.left + sx + 16, window.innerWidth - 240),
      screenY: Math.min(rect.top  + sy,      window.innerHeight - 180),
      src: edgeSource,
      tgt: targetNode.id,
    }
    edgeSource = null
  }
</script>

<div class="wrap">
  <svg bind:this={svgEl} width="100%" height="100%"></svg>

  <!-- Recommendation panel: cross-network targets (both modes) -->
  {#if edgeSource && recommendations.length > 0}
    <div class="rec-panel" class:rec-panel-low={viewMode === 'global'}>
      <div class="rec-header">Suggested targets</div>
      {#each recommendations as rec}
        <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
        <div class="rec-item" on:click={() => selectRecommendation(rec)}>
          <span class="rec-dot" style="background:{NODE_COLOR[rec.type] ?? '#888'}"></span>
          <span class="rec-body">
            <span class="rec-text">{rec.text.length > 48 ? rec.text.slice(0, 48) + '…' : rec.text}</span>
            {#if rec.conversations?.[0]?.title}
              <span class="rec-conv">{rec.conversations[0].title.length > 28 ? rec.conversations[0].title.slice(0, 28) + '…' : rec.conversations[0].title}</span>
            {/if}
          </span>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Edit mode hint banner -->
  {#if editMode === 'addEdge' && !edgePicker}
    <div class="mode-hint">
      {edgeSource ? 'Now click target on canvas or pick from list →' : 'Click a source node to start'}
    </div>
  {:else if editMode === 'addNode'}
    <div class="mode-hint">Double-click on canvas to place a node</div>
  {:else if editMode === 'delete'}
    <div class="mode-hint">Click a node or edge to delete it</div>
  {/if}

  <!-- Add node form -->
  {#if addNodeScreenPos}
    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
    <div class="overlay-backdrop" on:click={cancelOverlay}></div>
    <div class="overlay-form" style="left:{addNodeScreenPos.x}px; top:{addNodeScreenPos.y}px">
      <div class="form-title">Add Belief Node</div>
      <!-- svelte-ignore a11y_autofocus -->
      <input
        bind:value={addNodeForm.text}
        placeholder="Belief statement…"
        maxlength="80"
        autofocus
        on:keydown={e => {
          if (e.key === 'Enter') confirmAddNode()
          if (e.key === 'Escape') cancelOverlay()
        }}
      />
      <select bind:value={addNodeForm.type}>
        <option value="claim">Claim</option>
        <option value="evidence">Evidence</option>
        <option value="conclusion">Conclusion</option>
        <option value="constraint">Constraint</option>
        <option value="other">Other</option>
      </select>
      <div class="form-btns">
        <button class="primary" on:click={confirmAddNode}>Add</button>
        <button on:click={cancelOverlay}>Cancel</button>
      </div>
    </div>
  {/if}

  <!-- Edge relation picker -->
  {#if edgePicker}
    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
    <div class="overlay-backdrop" on:click={cancelOverlay}></div>
    <div class="overlay-form" style="left:{edgePicker.screenX}px; top:{edgePicker.screenY}px">
      <div class="form-title">Edge Relation</div>
      <div class="rel-options">
        {#each [['supports','Supports →','#6bcb77'], ['contradicts','Contradicts ✕','#f87171'], ['elaborates','Elaborates ‐‐','#8fa8c8'], ['causes','Causes →→','#f0a500'], ['alternatives','Alternatives ‐·‐','#a78bfa']] as [val, label, color]}
          <label class="rel-option" class:selected={relationType === val}>
            <input type="radio" bind:group={relationType} value={val} />
            <span style="color:{color}">{label}</span>
          </label>
        {/each}
      </div>
      <div class="form-btns">
        <button class="primary" on:click={confirmAddEdge}>Add Edge</button>
        <button on:click={cancelOverlay}>Cancel</button>
      </div>
    </div>
  {/if}
</div>

<style>
  .wrap { position: relative; width: 100%; height: 100%; }
  svg { display: block; background: var(--bg); }

  .mode-hint {
    position: absolute;
    bottom: 72px; left: 50%;
    transform: translateX(-50%);
    background: var(--accent);
    color: #fff;
    padding: 6px 20px;
    border-radius: 999px;
    font-size: 0.78rem;
    pointer-events: none;
    z-index: 15;
    white-space: nowrap;
    box-shadow: 0 2px 12px rgba(99,102,241,0.4);
  }

  .overlay-backdrop {
    position: fixed;
    inset: 0;
    z-index: 40;
  }

  .overlay-form {
    position: fixed;
    transform: translate(-8px, -8px);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    z-index: 50;
    display: flex;
    flex-direction: column;
    gap: 9px;
    min-width: 210px;
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.5);
  }
  .form-title { font-size: 0.8rem; font-weight: 600; color: var(--text); }

  .overlay-form input,
  .overlay-form select {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 5px;
    color: var(--text);
    padding: 6px 8px;
    font-size: 0.82rem;
    width: 100%;
    outline: none;
    font-family: inherit;
  }
  .overlay-form input:focus { border-color: var(--accent); }

  .rel-options { display: flex; flex-direction: column; gap: 3px; }
  .rel-option {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 8px;
    border-radius: 5px;
    cursor: pointer;
    font-size: 0.82rem;
    transition: background 0.1s;
  }
  .rel-option:hover    { background: var(--surface2); }
  .rel-option.selected { background: var(--surface2); }
  .rel-option input    { display: none; }

  .form-btns { display: flex; gap: 6px; }
  .form-btns button {
    flex: 1;
    padding: 6px;
    border-radius: 5px;
    border: 1px solid var(--border);
    cursor: pointer;
    font-size: 0.78rem;
    background: var(--surface2);
    color: var(--text);
    font-family: inherit;
    transition: background 0.1s;
  }
  .form-btns button:hover   { border-color: var(--text-muted); }

  /* Recommendation panel */
  .rec-panel {
    position: absolute;
    top: 60px; right: 14px;  /* conversation mode: just below toolbar */
    width: 230px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 0 6px;
    z-index: 20;
    box-shadow: 0 6px 24px rgba(0,0,0,0.45);
    display: flex;
    flex-direction: column;
    gap: 2px;
    animation: rec-in 0.15s ease;
  }
  /* In global mode, push the panel below the legend (~160px tall at top-right) */
  .rec-panel-low { top: 168px; }

  @keyframes rec-in {
    from { opacity: 0; transform: translateY(-6px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .rec-header {
    font-size: 0.67rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--text-muted);
    padding: 0 12px 6px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 2px;
  }
  .rec-item {
    display: flex;
    align-items: flex-start;
    gap: 9px;
    padding: 7px 12px;
    cursor: pointer;
    border-radius: 0;
    transition: background 0.1s;
  }
  .rec-item:hover { background: var(--surface2); }
  .rec-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
    margin-top: 4px;
  }
  .rec-body {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .rec-text {
    font-size: 0.79rem;
    color: var(--text);
    line-height: 1.35;
  }
  .rec-conv {
    font-size: 0.68rem;
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .form-btns button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  .form-btns button.primary:hover { opacity: 0.88; }
</style>
