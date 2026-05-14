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

  const NODE_COLOR   = { claim: '#93c5fd', evidence: '#fde68a', conclusion: '#6ee7b7', constraint: '#fdba74', other: '#cbd5e1' }
  const ORIGIN_COLOR = { user: '#f0e9de', model: '#a9baab', 'co-constructed': '#705a89' }

  function nodeFill(d) { return ORIGIN_COLOR[d.origin] ?? NODE_COLOR[d.type] ?? '#888' }
  const EDGE_COLOR = { supports: '#6bcb77', tension: '#f87171' }
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
  let mergeSource    = null   // nodeId of first click in merge mode
  let mergePicker    = null   // { screenX, screenY, nodeA, nodeB } — shown after 2nd click
  let mergeLabel     = ''     // user-editable label for the merged node
  let relationType   = 'supports'
  let edgeScheme     = 'other'
  let edgeAttackType = 'rebutting'
  let recommendations = []   // suggested cross-network targets while edgeSource is set
  let nodeSearchQuery = ''   // text filter inside the rec panel

  // Reactive mirrors of stores (readable in D3 callbacks as closure vars)
  $: viewMode      = $beliefViewMode
  $: focusedConvId = $beliefFocusedConvId
  $: editMode      = $beliefEditMode

  // Clear merge selection whenever merge mode is exited
  $: if (editMode !== 'merge') mergeSource = null
  // Clear edge source whenever addEdge mode is exited (toggle-off or mode switch)
  $: if (editMode !== 'addEdge') edgeSource = null

  // Cross-network link suggestions: work in both global and conversation modes.
  // Use full node list so cross-network targets appear even when zoomed into one conv.
  $: recommendations = edgeSource
    ? recommendLinks(edgeSource, nodes, visibleEdges)
    : []

  // Text search across all nodes (including other conversations) for cross-network linking
  $: nodeSearchResults = nodeSearchQuery.trim()
    ? nodes
        .filter(n => n.id !== edgeSource && !$beliefEdits.deletedNodes.has(n.id))
        .filter(n => {
          const q = nodeSearchQuery.toLowerCase()
          return (n.text ?? '').toLowerCase().includes(q) ||
                 (n.text_short ?? '').toLowerCase().includes(q)
        })
        .slice(0, 10)
    : []

  // Clear search when edgeSource is cancelled
  $: if (!edgeSource) nodeSearchQuery = ''

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

  // Computes edge-degree of each node id from a link list.
  // Used in conversation mode to surface recurring (high-connectivity) nodes.
  function computeNodeDegrees(links) {
    const deg = new Map()
    for (const l of links) {
      const s = typeof l.source === 'object' ? l.source.id : l.source
      const t = typeof l.target === 'object' ? l.target.id : l.target
      deg.set(s, (deg.get(s) || 0) + 1)
      deg.set(t, (deg.get(t) || 0) + 1)
    }
    return deg
  }

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
    // Separate marker for wavy tension edges: refX=0 so the tip lands exactly at the
    // path endpoint (which wavyPath already stops at the node surface).
    defs.append('marker')
      .attr('id', 'arrow-tension').attr('viewBox', '0 -4 8 8')
      .attr('refX', 0).attr('refY', 0)
      .attr('markerWidth', 6).attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path').attr('d', 'M0,-4L8,0L0,4').attr('fill', '#f87171')

    // Zoom behaviour
    const zoomBehavior = zoom()
      .scaleExtent([0.1, 4])
      .on('zoom', e => { currentTransform = e.transform; g.attr('transform', e.transform) })
    svgSel.call(zoomBehavior)

    // Click on SVG background → cancel edge source selection
    svgSel.on('click.cancelEdge', function() {
      if (get(beliefEditMode) !== 'addEdge') return
      edgeSource = null
    })

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
      // convMode is computed early so it can be used in simNodes pre-pinning below.
      const convMode    = curMode === 'conversation'
      const enteringConv = modeJustChanged && convMode

      // Build simNodes with stable pre-pinning:
      // • On mode entry → place near center (avoids stale global layout exploding).
      // • Otherwise → restore from posCache and PRE-PIN (fx/fy) every node that
      //   already has a known position. With all nodes pinned the sim can re-run
      //   for layout purposes (e.g. a new merged node) without moving anything else.
      const simNodes = visibleNodes.map(n => {
        const cached  = posCache.get(n.id)
        const useCache = !enteringConv && cached
        const x = useCache ? cached.x : (enteringConv ? W / 2 + (Math.random() - 0.5) * 120 : W / 2 + (Math.random() - 0.5) * 200)
        const y = useCache ? cached.y : (enteringConv ? H / 2 + (Math.random() - 0.5) * 120 : H / 2 + (Math.random() - 0.5) * 200)
        return {
          ...n, x, y,
          ...(convMode && !enteringConv && cached ? { fx: cached.x, fy: cached.y } : {}),
        }
      })
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
        const key = `${s}→${t}:${d.relation}`
        // Swell stroke then fade before committing deletion
        select(event.currentTarget)
          .transition().duration(80).attr('stroke-width', 5).attr('opacity', 1)
          .transition().duration(140).attr('stroke-width', 0).attr('opacity', 0)
          .on('end', () => {
            beliefEdits.update(ed => ({
              ...ed,
              deletedEdges: new Set([...ed.deletedEdges, key]),
            }))
          })
      }

      const straightLinks = simLinks.filter(e => e.relation !== 'tension')
      const wavyLinks     = simLinks.filter(e => e.relation === 'tension')

      const linkLine = linkGroup.selectAll('.link-line').data(straightLinks).join('line')
        .attr('class', d => `link link-line link-${d.relation}`)
        .attr('stroke', EDGE_COLOR.supports)
        .attr('stroke-width', 1.5)
        .attr('stroke-dasharray', null)
        .attr('marker-end', 'url(#arrow-supports)')
        .attr('opacity', 0.65)
        .on('click', edgeDeleteHandler)
      linkLine.selectAll('title').data(d => [d]).join('title')
        .text(d => d.scheme && d.scheme !== 'other' ? `supports · ${d.scheme}` : 'supports')

      const linkWavy = linkGroup.selectAll('.link-wavy').data(wavyLinks).join('path')
        .attr('class', 'link link-wavy link-tension')
        .attr('stroke', EDGE_COLOR.tension)
        .attr('stroke-width', 2)
        .attr('fill', 'none')
        .attr('marker-end', 'url(#arrow-tension)')
        .attr('opacity', 0.72)
        .on('click', edgeDeleteHandler)
      linkWavy.selectAll('title').data(d => [d]).join('title')
        .text(d => d.attack_type ? `tension · ${d.attack_type}` : 'tension')

      // ── Nodes ────────────────────────────────────────────────────────────────
      const node = nodeGroup.selectAll('.node-g').data(simNodes, d => d.id).join('g')
        .attr('class', 'node-g')
        .style('cursor', 'pointer')
        .call(
          drag()
            .on('start', (event, d) => {
              // In conversation mode all other nodes are pinned (fx/fy set after sim
              // settles), so restarting the sim here only moves the dragged node.
              if (!event.active) simulation.alphaTarget(0.3).restart()
              d.fx = d.x; d.fy = d.y
            })
            .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
            .on('end',  (event, d) => {
              if (!event.active) simulation.alphaTarget(0)
              if (convMode) {
                // Re-pin at drop position so the graph stays static
                d.fx = d.x; d.fy = d.y
              } else {
                d.fx = null; d.fy = null
              }
            })
        )
        .on('click', (event, d) => {
          event.stopPropagation()
          const mode = get(beliefEditMode)

          if (mode === 'delete') {
            // Swell then collapse ("pop") before committing deletion
            const el = nodeGroup.selectAll('.node-g').filter(n => n.id === d.id)
            const px = d.x ?? 0, py = d.y ?? 0
            el
              .transition().duration(70)
              .attr('transform', `translate(${px},${py}) scale(1.4)`)
              .style('opacity', '0.7')
              .transition().duration(120)
              .attr('transform', `translate(${px},${py}) scale(0)`)
              .style('opacity', '0')
              .on('end', () => {
                beliefEdits.update(ed => ({
                  ...ed,
                  deletedNodes: new Set([...ed.deletedNodes, d.id]),
                }))
              })
            return
          }

          if (mode === 'merge') {
            if (mergeSource === null) {
              mergeSource = d.id
              // Amber dashed ring marks the first node
              const r = d._w != null ? d._w / 2 + 9 : nodeRadius(d) + 9
              nodeGroup.selectAll('.node-g').filter(n => n.id === d.id)
                .append('circle').attr('class', 'merge-ring')
                .attr('r', r)
                .attr('fill', 'none')
                .attr('stroke', '#f59e0b')
                .attr('stroke-width', 2.5)
                .attr('stroke-dasharray', '5 3')
                .attr('opacity', 0.95)
                .attr('pointer-events', 'none')
            } else if (mergeSource !== d.id) {
              const srcNode = simNodes.find(n => n.id === mergeSource)
              nodeGroup.selectAll('.merge-ring').remove()
              mergeSource = null
              if (srcNode) {
                // Show label-editing overlay at the midpoint of the two nodes
                const mx = (srcNode.x + d.x) / 2
                const my = (srcNode.y + d.y) / 2
                const rect = svgEl.getBoundingClientRect()
                const [sx, sy] = currentTransform.apply([mx, my])
                mergePicker = {
                  screenX: Math.min(rect.left + sx, window.innerWidth  - 290),
                  screenY: Math.min(rect.top  + sy, window.innerHeight - 230),
                  nodeA: srcNode,
                  nodeB: d,
                }
                mergeLabel = srcNode.text_short ?? srcNode.text?.slice(0, 30) ?? ''
              }
            }
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

          // Collect normalized edges for the detail panel
          const nodeId = d.id
          const nodeEdges = visibleEdges
            .filter(e => {
              const s = typeof e.source === 'object' ? e.source.id : e.source
              const t = typeof e.target === 'object' ? e.target.id : e.target
              return s === nodeId || t === nodeId
            })
            .map(e => {
              const s = typeof e.source === 'object' ? e.source.id : e.source
              const t = typeof e.target === 'object' ? e.target.id : e.target
              const isOut  = s === nodeId
              const peerId = isOut ? t : s
              const peer   = visibleNodes.find(n => n.id === peerId)
              return {
                relation:    e.relation,
                scheme:      e.scheme      ?? null,
                attack_type: e.attack_type ?? null,
                direction:   isOut ? 'out' : 'in',
                peerText:    peer?.text_short ?? peer?.text ?? peerId,
                peerType:    peer?.type ?? 'other',
              }
            })
          selectedItem.set({ type: 'belief', data: { ...d, _edges: nodeEdges } })
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
        const focusedConv = perConversation.find(c => c.id === get(beliefFocusedConvId))
        const canonToTurnSpan = new Map()
        if (focusedConv) {
          for (const rawNode of focusedConv.nodes) {
            const canonId = idToCanon.get(rawNode.id)
            if (canonId) canonToTurnSpan.set(canonId, new Set(rawNode.turn_indices ?? []).size)
          }
        }
        node.each(function(d) {
          const g = select(this)
          const edited = get(beliefEdits).texts.get(d.id)
          const label = edited ?? d.text_short ?? (d.text ?? '').slice(0, 26)
          const w = Math.max(80, label.length * 6.2 + 28)
          const h = 28
          d._w = w; d._h = h   // store for collision + selection ring sizing
          d._recurring = (canonToTurnSpan.get(d.id) ?? 0) >= 5
          // Recurring pattern ring rendered below the pill so it shows behind it
          if (d._recurring) {
            g.append('ellipse')
              .attr('rx', w / 2 + 7).attr('ry', h / 2 + 7)
              .attr('fill', 'none')
              .attr('stroke', '#f59e0b')
              .attr('stroke-width', 2)
              .attr('stroke-dasharray', '5 3')
              .attr('opacity', 0.85)
              .attr('pointer-events', 'none')
              .attr('class', 'recurring-ring')
          }
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
            .attr('fill', '#2b2b2b')
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
          .attr('dy', d => nodeRadius(d) + 12)
          .attr('text-anchor', 'middle')
          .attr('font-size', '10px')
          .attr('fill', '#2b2b2b')
          .attr('pointer-events', 'none')
          .text(d => {
            const edited = get(beliefEdits).texts.get(d.id)
            const t = edited ?? d.text_short ?? d.text ?? ''
            return t.length > 30 ? t.slice(0, 30) + '…' : t
          })
      }

      // ── Selection ring (white ring around currently selected belief node) ────
      function applySelRing(selItem) {
        nodeGroup.selectAll('.sel-ring').remove()
        const sid = selItem?.type === 'belief' ? selItem?.data?.id : null
        if (!sid) return
        const vm = get(beliefViewMode)
        nodeGroup.selectAll('.node-g').filter(d => d.id === sid)
          .append('circle')
          .attr('class', 'sel-ring')
          .attr('r', d => vm === 'conversation'
            ? (d._w ?? 80) / 2 + 6
            : nodeRadius(d) + 7)
          .attr('fill', 'none')
          .attr('stroke', '#6366f1')
          .attr('stroke-width', 2.5)
          .attr('opacity', 0.9)
          .attr('pointer-events', 'none')
      }
      applySelRing(get(selectedItem))
      // Expose for imperative updates so selection changes don't need a full re-render
      window.__updateSelRing = applySelRing

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
      simulation = forceSimulation(simNodes)
        .velocityDecay(convMode ? 0.55 : 0.4)
        .alphaDecay(convMode ? 0.05 : 0.0228)
        .force('link',    forceLink(simLinks).id(d => d.id).distance(convMode ? 80 : 65).strength(0.6))
        .force('charge',  forceManyBody().strength(convMode ? -380 : -280))
        .force('center',  forceCenter(W / 2, H / 2))
        .force('collide', forceCollide().radius(d =>
          convMode ? (d._w ?? 80) / 2 + 10 : nodeRadius(d) + 10))
        .force('x', forceX(W / 2).strength(convMode ? 0.08 : 0.03))
        .force('y', forceY(H / 2).strength(convMode ? 0.08 : 0.03))
        .on('end', () => {
          // Pin every node once the layout settles so the graph is static;
          // dragging one node won't disturb the rest.
          if (convMode) simNodes.forEach(n => { n.fx = n.x; n.fy = n.y })
        })
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
            .attr('font-size', '10px')
            .attr('fill', '#2b2b2b')
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
  // Selection changes are handled imperatively via __updateSelRing — excluded from
  // the re-render key so clicking a node never restarts the simulation.
  $: window.__updateSelRing?.($selectedItem)

  let prevKey = ''
  afterUpdate(() => {
    const key = [
      visibleNodes.map(n => n.id).join(','),
      visibleEdges.length,
      viewMode,
      focusedConvId,
      editMode,
      edgeSource,
      $beliefEdits.texts.size,
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
    const edge = { source: edgePicker.src, target: edgePicker.tgt, relation: relationType }
    if (relationType === 'supports') edge.scheme = edgeScheme
    if (relationType === 'tension')  edge.attack_type = edgeAttackType
    beliefEdits.update(ed => ({ ...ed, edges: [...ed.edges, edge] }))
    edgePicker     = null
    relationType   = 'supports'
    edgeScheme     = 'other'
    edgeAttackType = 'rebutting'
  }

  function confirmMerge() {
    if (!mergePicker) return
    doMerge(mergePicker.nodeA, mergePicker.nodeB, mergeLabel)
    mergePicker = null
    mergeLabel  = ''
  }

  function cancelOverlay() {
    addNodeScreenPos = null
    addNodeGraphPos  = null
    edgePicker       = null
    edgeSource       = null
    mergePicker      = null
    mergeLabel       = ''
    relationType     = 'supports'
    edgeScheme       = 'other'
    edgeAttackType   = 'rebutting'
  }

  // Merge two nodes: redirect all their edges to a new canonical node, then delete both.
  // labelOverride: user-supplied label from the merge overlay (falls back to nodeA.text).
  function doMerge(nodeA, nodeB, labelOverride = null) {
    const mergedId = `merged_${Date.now()}`
    const ax = posCache.get(nodeA.id)?.x ?? nodeA.x ?? 0
    const ay = posCache.get(nodeA.id)?.y ?? nodeA.y ?? 0
    const bx = posCache.get(nodeB.id)?.x ?? nodeB.x ?? 0
    const by = posCache.get(nodeB.id)?.y ?? nodeB.y ?? 0
    posCache.set(mergedId, { x: (ax + bx) / 2, y: (ay + by) / 2 })

    const label = (labelOverride?.trim()) || nodeA.text || 'Merged node'
    const merged = {
      id: mergedId,
      text:       label,
      text_short: label.length > 22 ? label.slice(0, 22) + '…' : label,
      text_long:  `${nodeA.text_long ?? nodeA.text} · ${nodeB.text_long ?? nodeB.text}`,
      type:       nodeA.type,
      origin:     nodeA.origin === nodeB.origin ? nodeA.origin : 'co-constructed',
      frequency:  (nodeA.frequency ?? 1) + (nodeB.frequency ?? 1),
      conversations: [...new Map([
        ...(nodeA.conversations ?? []), ...(nodeB.conversations ?? [])
      ].map(c => [c.id, c])).values()],
      shared:    nodeA.shared || nodeB.shared,
      firstDate: nodeA.firstDate ?? nodeB.firstDate,
      _merged:   true,
    }

    const aId = nodeA.id, bId = nodeB.id
    const edgeKey = e => {
      const s = typeof e.source === 'object' ? e.source.id : e.source
      const t = typeof e.target === 'object' ? e.target.id : e.target
      return `${s}→${t}:${e.relation}`
    }
    const delEdgeKeys = new Set()
    const remappedEdges = []

    for (const e of visibleEdges) {
      const s = typeof e.source === 'object' ? e.source.id : e.source
      const t = typeof e.target === 'object' ? e.target.id : e.target
      if (s !== aId && s !== bId && t !== aId && t !== bId) continue
      delEdgeKeys.add(edgeKey(e))
      const ns = (s === aId || s === bId) ? mergedId : s
      const nt = (t === aId || t === bId) ? mergedId : t
      if (ns !== nt) remappedEdges.push({ source: ns, target: nt, relation: e.relation })
    }

    beliefEdits.update(ed => {
      const kept = ed.edges.filter(e =>
        e.source !== aId && e.source !== bId && e.target !== aId && e.target !== bId)
      const remappedEdit = ed.edges
        .filter(e => e.source === aId || e.source === bId || e.target === aId || e.target === bId)
        .map(e => ({
          ...e,
          source: (e.source === aId || e.source === bId) ? mergedId : e.source,
          target: (e.target === aId || e.target === bId) ? mergedId : e.target,
        }))
        .filter(e => e.source !== e.target)
      return {
        ...ed,
        nodes:        [...ed.nodes, merged],
        deletedNodes: new Set([...ed.deletedNodes, aId, bId]),
        deletedEdges: new Set([...ed.deletedEdges, ...delEdgeKeys]),
        edges:        [...kept, ...remappedEdit, ...remappedEdges],
      }
    })
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
  <svg
    bind:this={svgEl}
    width="100%" height="100%"
    class:mode-delete={editMode === 'delete'}
    class:mode-merge={editMode === 'merge'}
  ></svg>

  <!-- Recommendation panel: search + Jaccard suggestions (shown whenever a source is selected) -->
  {#if edgeSource}
    <div class="rec-panel" class:rec-panel-low={viewMode === 'global'}>
      <div class="rec-search">
        <!-- svelte-ignore a11y_autofocus -->
        <input
          class="rec-search-input"
          placeholder="Search nodes to link…"
          bind:value={nodeSearchQuery}
          autofocus
          on:keydown={e => { if (e.key === 'Escape') nodeSearchQuery = ''; e.stopPropagation(); }}
        />
      </div>
      {#if nodeSearchQuery.trim()}
        {#if nodeSearchResults.length > 0}
          <div class="rec-header">Search results</div>
          {#each nodeSearchResults as rec}
            <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
            <div class="rec-item" on:click={() => { selectRecommendation(rec); nodeSearchQuery = ''; }}>
              <span class="rec-dot" style="background:{NODE_COLOR[rec.type] ?? '#888'}"></span>
              <span class="rec-body">
                <span class="rec-text">{rec.text.length > 48 ? rec.text.slice(0, 48) + '…' : rec.text}</span>
                {#if rec.conversations?.[0]?.title}
                  <span class="rec-conv">{rec.conversations[0].title.length > 28 ? rec.conversations[0].title.slice(0, 28) + '…' : rec.conversations[0].title}</span>
                {/if}
              </span>
            </div>
          {/each}
        {:else}
          <div class="rec-empty">No nodes match "{nodeSearchQuery}"</div>
        {/if}
      {:else if recommendations.length > 0}
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
      {:else}
        <div class="rec-empty">Type to search for any node</div>
      {/if}
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
  {:else if editMode === 'merge'}
    <div class="mode-hint mode-hint-merge">
      {mergeSource ? 'Now click the second node to merge →' : 'Click the first node to merge'}
    </div>
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
        {#each [['supports','Supports →','#6bcb77'], ['tension','Tension ≈','#f87171']] as [val, label, color]}
          <label class="rel-option" class:selected={relationType === val}>
            <input type="radio" bind:group={relationType} value={val} />
            <span style="color:{color}">{label}</span>
          </label>
        {/each}
      </div>
      {#if relationType === 'supports'}
        <select bind:value={edgeScheme}>
          <option value="other">Scheme: general</option>
          <option value="causal">Causal</option>
          <option value="evidential">Evidential</option>
          <option value="expert">Expert / authority</option>
          <option value="analogical">Analogical</option>
          <option value="consequence">Consequence</option>
          <option value="example">Example</option>
        </select>
      {:else}
        <select bind:value={edgeAttackType}>
          <option value="rebutting">Rebutting (content)</option>
          <option value="undercutting">Undercutting (inference)</option>
        </select>
      {/if}
      <div class="form-btns">
        <button class="primary" on:click={confirmAddEdge}>Add Edge</button>
        <button on:click={cancelOverlay}>Cancel</button>
      </div>
    </div>
  {/if}

  <!-- Merge label overlay -->
  {#if mergePicker}
    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
    <div class="overlay-backdrop" on:click={cancelOverlay}></div>
    <div class="overlay-form" style="left:{mergePicker.screenX}px; top:{mergePicker.screenY}px">
      <div class="form-title">Merge Nodes</div>
      <div class="merge-preview">
        <span class="merge-tag">{(mergePicker.nodeA.text_short ?? mergePicker.nodeA.text ?? '').slice(0, 22)}</span>
        <span class="merge-plus">+</span>
        <span class="merge-tag">{(mergePicker.nodeB.text_short ?? mergePicker.nodeB.text ?? '').slice(0, 22)}</span>
      </div>
      <span class="form-sublabel">Label for merged node</span>
      <!-- svelte-ignore a11y_autofocus -->
      <input
        bind:value={mergeLabel}
        placeholder="Merged node label…"
        maxlength="60"
        autofocus
        on:keydown={e => {
          if (e.key === 'Enter') confirmMerge()
          if (e.key === 'Escape') cancelOverlay()
        }}
      />
      <div class="form-btns">
        <button class="primary merge-confirm" on:click={confirmMerge}>Merge</button>
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

  /* Cursor feedback for edit modes */
  svg.mode-delete { cursor: crosshair; }
  svg.mode-merge  { cursor: cell; }

  .merge-preview {
    display: flex;
    align-items: center;
    gap: 5px;
    flex-wrap: wrap;
  }
  .merge-tag {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 2px 7px;
    font-size: 0.74rem;
    color: var(--text);
    max-width: 110px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .merge-plus {
    color: #f59e0b;
    font-weight: 700;
    font-size: 1rem;
    line-height: 1;
  }
  .form-sublabel {
    font-size: 0.71rem;
    color: var(--text-muted);
  }
  .merge-confirm.primary {
    background: #b45309;
    border-color: #b45309;
  }
  .merge-confirm.primary:hover { opacity: 0.88; }

  /* Merge hint uses amber accent to match the ring colour */
  .mode-hint-merge {
    background: #b45309;
    box-shadow: 0 2px 12px rgba(180,83,9,0.4);
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
  .rec-search {
    padding: 8px 10px 6px;
    border-bottom: 1px solid var(--border);
  }
  .rec-search-input {
    width: 100%;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 5px;
    color: var(--text);
    padding: 5px 8px;
    font-size: 0.8rem;
    outline: none;
    font-family: inherit;
    box-sizing: border-box;
  }
  .rec-search-input:focus { border-color: var(--accent); }
  .rec-empty {
    padding: 10px 12px;
    font-size: 0.76rem;
    color: var(--text-muted);
    text-align: center;
    font-style: italic;
  }
  .rec-header {
    font-size: 0.67rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--text-muted);
    padding: 6px 12px 6px;
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
