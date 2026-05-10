<script>
  // @ts-nocheck
  import { onMount } from 'svelte'
  import { scaleTime, scaleLinear } from 'd3-scale'
  import { axisBottom } from 'd3-axis'
  import { select } from 'd3-selection'
  import { area, stack, stackOffsetSilhouette, curveMonotoneX } from 'd3-shape'
  import { selectedItem } from '../../stores.js'

  export let data = []

  // ── Categories derived from extracted data ────────────────────────────────
  const PALETTE = ['#4e9af1', '#6bcb77', '#f0a500', '#c77dff', '#ff6b6b', '#4ecdc4', '#ffd93d', '#ff8c42']

  $: cats = (() => {
    const seen = new Set()
    for (const d of data)
      for (const s of (d.method_spans ?? []))
        if (s.label) seen.add(s.label)
    return [...seen].sort()
  })()

  $: catColor = Object.fromEntries(cats.map((c, i) => [c, PALETTE[i % PALETTE.length]]))

  // ── Layout constants ───────────────────────────────────────────────────────
  $: activeCats = cats.filter(cat => streamRows.some(r => r[cat] > 0))
  $: STREAM_H = Math.max(110, activeCats.length * 20 + 50)
  const ROW_H   = 24
  const LABEL_W = 172
  const R_MARGIN = 24
  const T_MARGIN = 10
  const B_MARGIN = 32

  // ── Derived data ───────────────────────────────────────────────────────────
  $: eligible = data
    .filter(d => d.method_spans?.length)
    .sort((a, b) => a.date.localeCompare(b.date))

  // One row per unique span text; sorted by label group then first occurrence
  $: methodRows = (() => {
    const map = new Map()
    for (const d of eligible) {
      for (const s of (d.method_spans ?? [])) {
        const key = s.span.toLowerCase().trim()
        if (!map.has(key)) map.set(key, { text: s.span, label: s.label, occurrences: [] })
        map.get(key).occurrences.push({ date: new Date(d.date), conv: d })
      }
    }
    return [...map.values()].sort((a, b) => {
      if (a.label !== b.label) return a.label.localeCompare(b.label)
      return a.occurrences[0].date - b.occurrences[0].date
    })
  })()

  const DATE_MIN = new Date('2026-03-23')
  const DATE_MAX = new Date('2026-04-25')

  // ── Container sizing ───────────────────────────────────────────────────────
  let container, presenceAxisEl, streamAxisEl
  let width = 900

  $: xScale = scaleTime()
    .domain([DATE_MIN, DATE_MAX])
    .range([LABEL_W, width - R_MARGIN])

  // ── Stream chart data ──────────────────────────────────────────────────────
  $: uniqueDates = [...new Set(eligible.map(d => d.date))].sort()

  $: streamRows = uniqueDates.map(date => {
    const convs = eligible.filter(d => d.date === date)
    const row = { date: new Date(date) }
    for (const cat of cats) {
      row[cat] = convs.reduce((n, d) =>
        n + (d.method_spans ?? []).filter(s => s.label === cat).length, 0)
    }
    return row
  })

  $: stackedStream = (() => {
    if (!streamRows.length) return []
    try {
      return stack().keys(cats).offset(stackOffsetSilhouette)(streamRows)
    } catch { return [] }
  })()

  $: streamExtent = (() => {
    let lo = 0, hi = 0
    for (const layer of stackedStream)
      for (const d of layer) {
        if (d[0] < lo) lo = d[0]
        if (d[1] > hi) hi = d[1]
      }
    return [lo, hi]
  })()

  $: streamY = scaleLinear()
    .domain(streamExtent)
    .range([STREAM_H - 4, T_MARGIN])
    .nice()

  $: areaGen = area()
    .x(d => xScale(d.data.date))
    .y0(d => streamY(d[0]))
    .y1(d => streamY(d[1]))
    .curve(curveMonotoneX)

  // ── Dot radius encodes conversation duration ───────────────────────────────
  function dotR(conv) {
    return Math.max(4, Math.log1p(conv.duration_minutes ?? 0) * 2.2)
  }

  // ── Axes ───────────────────────────────────────────────────────────────────
  $: if (presenceAxisEl && width) {
    select(presenceAxisEl).call(
      axisBottom(xScale).ticks(8)
        .tickFormat(d => d.toLocaleString('en-US', { month: 'short', day: 'numeric' }))
        .tickSize(4)
    )
  }

  $: if (streamAxisEl && width) {
    select(streamAxisEl).call(
      axisBottom(xScale).ticks(8)
        .tickFormat(d => d.toLocaleString('en-US', { month: 'short', day: 'numeric' }))
        .tickSize(3)
    )
  }

  function handleResize() {
    if (container) width = container.clientWidth
  }
  onMount(() => {
    handleResize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  })

  let tooltip = null
</script>

<div class="wrap" bind:this={container}>

  <!-- ── Stream chart ─────────────────────────────────────────────────── -->
  <div class="stream-panel">
    <div class="panel-label">Methodology over time</div>
    <svg {width} height={STREAM_H + B_MARGIN}>
      <defs>
        <clipPath id="stream-clip">
          <rect x={LABEL_W} y={0} width={width - LABEL_W - R_MARGIN} height={STREAM_H} />
        </clipPath>
      </defs>

      <!-- Category labels on left -->
      {#each cats as cat, i}
        <text
          x={LABEL_W - 8}
          y={STREAM_H / 2 + (i - Math.floor(cats.length / 2)) * 12}
          text-anchor="end"
          font-size="9"
          fill={catColor[cat]}
          opacity="0.75"
        >{cat}</text>
      {/each}

      <!-- Stream areas -->
      <g clip-path="url(#stream-clip)">
        {#each stackedStream as layer, i}
          <path d={areaGen(layer)} fill={catColor[cats[i]]} opacity="0.55" />
        {/each}
        <line
          x1={LABEL_W} x2={width - R_MARGIN}
          y1={streamY(0)} y2={streamY(0)}
          stroke="var(--border)" stroke-width="0.5"
        />
      </g>

      <g bind:this={streamAxisEl} transform="translate(0,{STREAM_H})" />
    </svg>
  </div>

  <!-- ── Method presence chart ──────────────────────────────────────────── -->
  <div class="presence-scroll">
    {#if methodRows.length === 0}
      <div class="empty">No methods extracted yet — run <code>python -m pipeline.methods</code> to populate.</div>
    {:else}
      <svg {width} height={methodRows.length * ROW_H + B_MARGIN}>

        <!-- Date grid lines -->
        {#each uniqueDates as date}
          <line
            x1={xScale(new Date(date))} x2={xScale(new Date(date))}
            y1={0} y2={methodRows.length * ROW_H}
            stroke="var(--border)" stroke-dasharray="2,4" stroke-width="0.8"
            opacity="0.5"
          />
        {/each}

        <!-- One row per unique method/tool -->
        {#each methodRows as method, i}
          {@const y   = i * ROW_H}
          {@const col = catColor[method.label] ?? '#4a5568'}

          <!-- Row background -->
          <rect x={0} y={y} {width} height={ROW_H}
            fill={i % 2 === 0 ? 'var(--surface)' : 'var(--bg)'} opacity="0.4" />

          <!-- Method name label -->
          <text
            x={LABEL_W - 8} y={y + ROW_H / 2 + 4}
            text-anchor="end" font-size="9.5" fill={col} opacity="0.9"
          >{method.text}</text>

          <!-- Connector line spanning first → last occurrence -->
          {#if method.occurrences.length > 1}
            <line
              x1={xScale(method.occurrences[0].date)}
              x2={xScale(method.occurrences[method.occurrences.length - 1].date)}
              y1={y + ROW_H / 2} y2={y + ROW_H / 2}
              stroke={col} stroke-width="1" opacity="0.18"
            />
          {/if}

          <!-- Occurrence dots (one per conversation) -->
          {#each method.occurrences as occ}
            {@const cx = xScale(occ.date)}
            {@const r  = dotR(occ.conv)}
            <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
            <circle
              {cx} cy={y + ROW_H / 2} {r}
              fill={col} opacity="0.75"
              stroke="var(--bg)" stroke-width="1"
              style="cursor:pointer"
              on:click={() => {
                if ($selectedItem?.type === 'method' && $selectedItem.data === occ.conv) {
                  selectedItem.set(null)
                } else {
                  selectedItem.set({ type: 'method', data: occ.conv })
                }
              }}
              on:mouseenter={e => tooltip = { x: e.clientX, y: e.clientY, conv: occ.conv, method: method.text }}
              on:mouseleave={() => tooltip = null}
            />
          {/each}
        {/each}

        <!-- Divider: labels | chart -->
        <line x1={LABEL_W} x2={LABEL_W} y1={0} y2={methodRows.length * ROW_H}
          stroke="var(--border)" stroke-width="1" />

        <!-- X-axis -->
        <g bind:this={presenceAxisEl} transform="translate(0,{methodRows.length * ROW_H})" />
      </svg>
    {/if}
  </div>

  <!-- Legend -->
  <div class="legend">
    {#each cats as cat}
      <span class="leg-item">
        <span class="leg-dot" style="background:{catColor[cat]}"></span>
        {cat}
      </span>
    {/each}
    <span class="leg-item muted">dot size = duration</span>
  </div>

  <!-- Tooltip -->
  {#if tooltip}
    <div class="tooltip" style="left:{tooltip.x + 14}px; top:{tooltip.y - 10}px">
      <strong>{tooltip.conv.title}</strong>
      <span>{tooltip.conv.date} · {tooltip.conv.duration_minutes < 1 ? '< 1 min' : Math.round(tooltip.conv.duration_minutes) + ' min'}</span>
      <span class="method-text">{tooltip.method}</span>
      {#if tooltip.conv.method_spans?.length}
        {#each tooltip.conv.method_spans.filter(s => s.span !== tooltip.method).slice(0, 3) as s}
          <span>{s.span}</span>
        {/each}
      {/if}
    </div>
  {/if}
</div>

<style>
  .wrap {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .stream-panel {
    flex-shrink: 0;
    border-bottom: 1px solid var(--border);
    background: var(--surface);
    position: relative;
  }
  .panel-label {
    position: absolute;
    top: 8px; left: 8px;
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--text-muted);
    opacity: 0.6;
    pointer-events: none;
  }

  .presence-scroll {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
  }
  .empty {
    padding: 32px 24px;
    font-size: 0.82rem;
    color: var(--text-muted);
    line-height: 1.6;
  }
  .empty code {
    font-family: monospace;
    background: var(--surface2);
    padding: 1px 5px;
    border-radius: 3px;
  }

  :global(.presence-scroll text)  { fill: var(--text-muted); font-size: 10px; }
  :global(.presence-scroll line, .presence-scroll path) { stroke: var(--border); }
  :global(.stream-panel text)     { fill: var(--text-muted); font-size: 10px; }
  :global(.stream-panel line, .stream-panel path) { stroke: var(--border); }

  .legend {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 7px 18px;
    border-top: 1px solid var(--border);
    background: var(--surface);
    font-size: 0.72rem;
    color: var(--text-muted);
  }
  .leg-item { display: flex; align-items: center; gap: 5px; }
  .leg-dot  { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .muted    { margin-left: auto; font-style: italic; opacity: 0.6; }

  .tooltip {
    position: fixed;
    pointer-events: none;
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 8px 12px;
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 0.78rem;
    color: var(--text);
    z-index: 200;
    max-width: 260px;
  }
  .tooltip strong      { font-size: 0.82rem; }
  .tooltip span        { color: var(--text-muted); }
  .tooltip .method-text {
    color: var(--text);
    font-weight: 600;
    font-size: 0.8rem;
  }
</style>
