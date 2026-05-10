<script>
  // @ts-nocheck
  import { onMount } from 'svelte'
  import { scaleLinear, scaleSqrt, scaleTime } from 'd3-scale'
  import { axisBottom, axisLeft } from 'd3-axis'
  import { select } from 'd3-selection'
  import { brushX } from 'd3-brush'
  import { polygonHull } from 'd3-polygon'
  import { selectedItem } from '../../stores.js'

  export let data = []

  let width = 800, height = 600
  let container, xAxisEl, yAxisEl, brushAxisEl, brushGroupEl
  let tooltip = null
  let filterRange = null   // { start: Date, end: Date } | null

  const BRUSH_H  = 72     // total height of bottom brush panel
  const HIST_H   = 46     // histogram bars height within brush panel
  const MARGIN   = { top: 24, right: 24, bottom: 44, left: 50 }

  const CLUSTERS = [
    { id: -1, label: 'Unclustered',              color: '#4a5568' },
    { id:  0, label: 'Dimensionality & algebra', color: '#4e9af1' },
    { id:  1, label: 'Academic reading',         color: '#f0a500' },
    { id:  2, label: 'Interactive viz',          color: '#6bcb77' },
    { id:  3, label: 'Data & social',            color: '#f87171' },
    { id:  4, label: 'Research project',         color: '#c77dff' },
  ]
  const colorOf = id => CLUSTERS.find(c => c.id === id)?.color ?? '#4a5568'

  // ── Scatter dimensions ────────────────────────────────────────────────────
  $: scatterH = height - BRUSH_H - 8
  $: innerW   = width - MARGIN.left - MARGIN.right
  $: innerH   = scatterH - MARGIN.top - MARGIN.bottom

  $: xScale = scaleLinear().domain([-9.5, -3.7]).range([0, innerW])
  $: yScale = scaleLinear().domain([4.2, 10.3]).range([innerH, 0])
  $: rScale = scaleSqrt().domain([0, 42]).range([4, 18])

  // Date range filter → visible points
  $: visibleData = filterRange
    ? data.filter(d => {
        const t = new Date(d.date)
        return t >= filterRange.start && t <= filterRange.end
      })
    : data

  // ── Hull computation ──────────────────────────────────────────────────────
  function expandHull(hull, pad) {
    const cx = hull.reduce((s, p) => s + p[0], 0) / hull.length
    const cy = hull.reduce((s, p) => s + p[1], 0) / hull.length
    return hull.map(([x, y]) => {
      const dx = x - cx, dy = y - cy
      const l = Math.sqrt(dx * dx + dy * dy) || 1
      return [x + dx / l * pad, y + dy / l * pad]
    })
  }

  $: hulls = CLUSTERS.filter(c => c.id !== -1).flatMap(c => {
    const pts = visibleData
      .filter(d => d.cluster_id === c.id)
      .map(d => [xScale(d.x), yScale(d.y)])
    if (!pts.length) return []
    if (pts.length < 3) {
      // Single or double point: render a soft circle around centroid
      const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length
      const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length
      return [{ ...c, type: 'circle', cx, cy, r: 36, labelX: cx, labelY: cy - 42 }]
    }
    const raw = polygonHull(pts)
    if (!raw) return []
    const exp = expandHull(raw, 22)
    const labelX = exp.reduce((s, p) => s + p[0], 0) / exp.length
    const labelY = Math.min(...exp.map(p => p[1])) - 10
    return [{ ...c, type: 'hull', points: exp, labelX, labelY }]
  })

  function hullD(pts) {
    return 'M' + pts.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join('L') + 'Z'
  }

  // ── Brush / histogram ─────────────────────────────────────────────────────
  const DATE_MIN = new Date('2026-03-24')
  const DATE_MAX = new Date('2026-04-23')
  $: timeScale = scaleTime()
    .domain([DATE_MIN, DATE_MAX])
    .range([MARGIN.left, width - MARGIN.right])

  $: histData = (() => {
    const counts = new Map()
    for (const d of data) {
      counts.set(d.date, (counts.get(d.date) ?? 0) + 1)
    }
    return Array.from(counts, ([date, count]) => ({ date: new Date(date), count }))
      .sort((a, b) => a.date - b.date)
  })()

  $: maxCount  = Math.max(1, ...histData.map(d => d.count))
  $: histYScale = scaleLinear().domain([0, maxCount]).range([HIST_H, 2])

  $: barW = histData.length > 1
    ? Math.max(4, (timeScale(histData[1].date) - timeScale(histData[0].date)) * 0.55)
    : 12

  // Brush setup (re-run when brushGroupEl or width changes)
  let brushBehavior
  function setupBrush() {
    if (!brushGroupEl) return
    brushBehavior = brushX()
      .extent([[MARGIN.left, 0], [width - MARGIN.right, HIST_H + 2]])
      .on('end', ({ selection }) => {
        if (!selection) { filterRange = null; return }
        const [x0, x1] = selection
        filterRange = { start: timeScale.invert(x0), end: timeScale.invert(x1) }
      })
    select(brushGroupEl).call(brushBehavior)
  }

  function clearBrush() {
    if (brushGroupEl && brushBehavior) {
      select(brushGroupEl).call(brushBehavior.move, null)
    }
    filterRange = null
  }

  // ── Axes ──────────────────────────────────────────────────────────────────
  $: if (xAxisEl && innerW > 0) {
    select(xAxisEl).call(axisBottom(xScale).ticks(5).tickSize(-innerH))
  }
  $: if (yAxisEl && innerH > 0) {
    select(yAxisEl).call(axisLeft(yScale).ticks(5).tickSize(-innerW))
  }
  $: if (brushAxisEl && width > 0) {
    select(brushAxisEl).call(
      axisBottom(timeScale).ticks(6).tickFormat(d => {
        const m = d.toLocaleString('en-US', { month: 'short' })
        const day = d.getDate()
        return `${m} ${day}`
      }).tickSize(4)
    )
  }

  function handleResize() {
    if (container) { width = container.clientWidth; height = container.clientHeight }
  }
  onMount(() => {
    handleResize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  })

  $: if (brushGroupEl && width) setupBrush()
</script>

<div class="wrap" bind:this={container}>
  <!-- ── Scatter SVG ──────────────────────────────────────────────────── -->
  <svg width={width} height={scatterH}>
    <defs>
      <clipPath id="scatter-clip">
        <rect width={innerW} height={innerH} />
      </clipPath>
    </defs>

    <g transform="translate({MARGIN.left},{MARGIN.top})">
      <!-- Axes -->
      <g bind:this={xAxisEl} class="axis" transform="translate(0,{innerH})" />
      <g bind:this={yAxisEl} class="axis" />

      <!-- Hull fills (under points) -->
      <g clip-path="url(#scatter-clip)">
        {#each hulls as h}
          {#if h.type === 'hull'}
            <path
              d={hullD(h.points)}
              fill={h.color}
              fill-opacity="0.09"
              stroke={h.color}
              stroke-opacity="0.4"
              stroke-width="1.5"
              stroke-dasharray="6,4"
              pointer-events="none"
            />
          {:else}
            <circle
              cx={h.cx} cy={h.cy} r={h.r}
              fill={h.color}
              fill-opacity="0.09"
              stroke={h.color}
              stroke-opacity="0.4"
              stroke-width="1.5"
              stroke-dasharray="6,4"
              pointer-events="none"
            />
          {/if}
        {/each}
      </g>

      <!-- Points -->
      <g clip-path="url(#scatter-clip)">
        {#each visibleData as d (d.id)}
          <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
          <circle
            cx={xScale(d.x)}
            cy={yScale(d.y)}
            r={rScale(d.human_turn_count ?? 1)}
            fill={colorOf(d.cluster_id)}
            opacity={tooltip?.d.id === d.id ? 1 : 0.78}
            stroke={tooltip?.d.id === d.id ? '#fff' : 'transparent'}
            stroke-width="1.5"
            style="cursor:pointer"
            on:mouseenter={e => tooltip = { x: e.clientX, y: e.clientY, d }}
            on:mouseleave={() => tooltip = null}
            on:click={() => {
              if ($selectedItem?.type === 'topic' && $selectedItem.data.id === d.id) {
                selectedItem.set(null)
              } else {
                selectedItem.set({ type: 'topic', data: d })
              }
            }}
          />
        {/each}
      </g>

      <!-- Hull cluster labels (on top of points) -->
      <g clip-path="url(#scatter-clip)">
        {#each hulls as h}
          <text
            x={h.labelX} y={h.labelY}
            text-anchor="middle"
            font-size="9.5"
            fill={h.color}
            opacity="0.85"
            pointer-events="none"
            font-weight="600"
            letter-spacing="0.03em"
          >{h.label}</text>
        {/each}
      </g>
    </g>

    <!-- Fade-out points outside filter (dim instead of hide for context) -->
  </svg>

  <!-- ── Brush panel ─────────────────────────────────────────────────── -->
  <svg width={width} height={BRUSH_H} class="brush-svg">
    <!-- Histogram bars -->
    {#each histData as h}
      <rect
        x={timeScale(h.date) - barW / 2}
        y={histYScale(h.count)}
        width={barW}
        height={HIST_H - histYScale(h.count)}
        fill="var(--accent)"
        opacity={filterRange ? 0.25 : 0.45}
        rx="2"
      />
      {#if filterRange}
        <!-- Highlighted bars within range -->
        {#if h.date >= filterRange.start && h.date <= filterRange.end}
          <rect
            x={timeScale(h.date) - barW / 2}
            y={histYScale(h.count)}
            width={barW}
            height={HIST_H - histYScale(h.count)}
            fill="var(--accent)"
            opacity="0.72"
            rx="2"
          />
        {/if}
      {/if}
    {/each}

    <!-- Brush group -->
    <g bind:this={brushGroupEl} />

    <!-- Time axis -->
    <g bind:this={brushAxisEl} transform="translate(0,{HIST_H + 4})" />

    <!-- Clear button (only when filter active) -->
    {#if filterRange}
      <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
      <text
        x={width - MARGIN.right - 2}
        y={HIST_H - 2}
        text-anchor="end"
        font-size="9"
        fill="var(--accent)"
        style="cursor:pointer"
        on:click={clearBrush}
      >✕ clear</text>
    {/if}
  </svg>

  <!-- Tooltip -->
  {#if tooltip}
    <div class="tooltip" style="left:{tooltip.x + 14}px; top:{tooltip.y - 10}px">
      <strong>{tooltip.d.title}</strong>
      <span>{tooltip.d.date}</span>
      <span>{tooltip.d.human_turn_count}H / {tooltip.d.ai_turn_count}A turns</span>
    </div>
  {/if}
</div>

<style>
  .wrap { position: relative; width: 100%; height: 100%; display: flex; flex-direction: column; }
  svg { display: block; }
  .brush-svg { flex-shrink: 0; }

  :global(.axis text)            { fill: var(--text-muted); font-size: 10px; }
  :global(.axis line, .axis path){ stroke: var(--border); }
  :global(.axis .tick line)      { stroke: var(--border); stroke-dasharray: 2,3; }

  :global(.brush-svg text)       { fill: var(--text-muted); font-size: 10px; }
  :global(.brush-svg line, .brush-svg path) { stroke: var(--border); }

  /* D3 brush appearance */
  :global(.selection) {
    fill: var(--accent);
    fill-opacity: 0.15;
    stroke: var(--accent);
    stroke-width: 1;
  }
  :global(.handle) { fill: var(--accent); fill-opacity: 0.6; }

  .tooltip {
    position: fixed;
    pointer-events: none;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 0.78rem;
    color: var(--text);
    z-index: 200;
    max-width: 240px;
  }
  .tooltip strong { font-size: 0.82rem; }
  .tooltip span   { color: var(--text-muted); }
</style>
