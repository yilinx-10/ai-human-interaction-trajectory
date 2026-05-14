<div class="legend">
  <!-- Node types -->
  <div class="section">
    <span class="header">Node type</span>

    <!-- Claim: rounded rect -->
    <div class="row">
      <svg width="22" height="16">
        <rect x="2" y="3" width="18" height="10" rx="2"
              fill="#93c5fd" stroke="#3a4060" stroke-width="1.2" opacity="0.9"/>
      </svg>
      <span>Claim</span>
    </div>

    <!-- Evidence: diamond -->
    <div class="row">
      <svg width="22" height="16">
        <polygon points="11,2 20,8 11,14 2,8"
                 fill="#fde68a" stroke="#3a4060" stroke-width="1.2" opacity="0.9"/>
      </svg>
      <span>Evidence</span>
    </div>

    <!-- Conclusion: circle -->
    <div class="row">
      <svg width="22" height="16">
        <circle cx="11" cy="8" r="6"
                fill="#6ee7b7" stroke="#3a4060" stroke-width="1.2" opacity="0.9"/>
      </svg>
      <span>Conclusion</span>
    </div>

    <!-- Constraint: down-pointing triangle -->
    <div class="row">
      <svg width="22" height="16">
        <polygon points="3,3 19,3 11,14"
                 fill="#fdba74" stroke="#3a4060" stroke-width="1.2" opacity="0.9"/>
      </svg>
      <span>Constraint</span>
    </div>

    <!-- Shared badge note -->
    <div class="row muted">
      <svg width="22" height="16">
        <circle cx="11" cy="8" r="6" fill="none" stroke="#888" stroke-width="1.2" stroke-dasharray="3,2"/>
        <circle cx="15" cy="4" r="3" fill="#6366f1" stroke="#3a4060" stroke-width="0.8"/>
      </svg>
      <span>Shared node</span>
    </div>

    <!-- Recurring pattern ring (conversation mode) -->
    <div class="row muted">
      <svg width="22" height="16">
        <ellipse cx="11" cy="8" rx="9" ry="6" fill="none" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="3,2"/>
      </svg>
      <span>Recurring (conv.)</span>
    </div>
  </div>

  <div class="divider"></div>

  <!-- Node origin -->
  <div class="section">
    <span class="header">Node origin</span>

    <!-- User-introduced -->
    <div class="row">
      <svg width="22" height="16">
        <circle cx="11" cy="8" r="6" fill="#f0e9de" stroke="#3a4060" stroke-width="1.2" opacity="0.9"/>
      </svg>
      <span>User</span>
    </div>

    <!-- Model-introduced -->
    <div class="row">
      <svg width="22" height="16">
        <circle cx="11" cy="8" r="6" fill="#a9baab" stroke="#3a4060" stroke-width="1.2" opacity="0.9"/>
      </svg>
      <span>Model</span>
    </div>

    <!-- Co-constructed: purple -->
    <div class="row">
      <svg width="22" height="16">
        <circle cx="11" cy="8" r="6" fill="#705a89" stroke="#3a4060" stroke-width="1.2" opacity="0.9"/>
      </svg>
      <span>Co-constructed</span>
    </div>
  </div>

  <div class="divider"></div>

  <!-- Edge relations -->
  <div class="section">
    <span class="header">Edge relation</span>

    <!-- Supports: solid green + arrowhead -->
    <div class="row">
      <svg width="34" height="14">
        <defs>
          <marker id="leg-arrow-supports" viewBox="0 -3 6 6" refX="5" refY="0"
                  markerWidth="4" markerHeight="4" orient="auto">
            <path d="M0,-3L6,0L0,3" fill="#6bcb77"/>
          </marker>
        </defs>
        <line x1="2" y1="7" x2="28" y2="7"
              stroke="#6bcb77" stroke-width="1.5"
              marker-end="url(#leg-arrow-supports)"/>
      </svg>
      <span>Supports</span>
    </div>

    <!-- Tension: wavy red + arrowhead -->
    <div class="row">
      <svg width="34" height="14">
        <defs>
          <marker id="leg-arrow-tension" viewBox="0 -3 6 6" refX="0" refY="0"
                  markerWidth="4" markerHeight="4" orient="auto">
            <path d="M0,-3L6,0L0,3" fill="#f87171"/>
          </marker>
        </defs>
        <path d="M2,7 Q6,3 10,7 Q14,11 18,7 Q22,3 26,7 L30,7"
              stroke="#f87171" stroke-width="1.5" fill="none"
              marker-end="url(#leg-arrow-tension)"/>
      </svg>
      <span>Tension</span>
    </div>
  </div>
</div>

<style>
  .legend {
    position: absolute;
    top: 16px; right: 16px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 14px;
    display: flex;
    gap: 16px;
    font-size: 0.75rem;
    color: var(--text-muted);
    z-index: 10;
  }
  .section { display: flex; flex-direction: column; gap: 6px; }
  .header {
    font-weight: 600;
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-muted);
    margin-bottom: 2px;
  }
  .row { display: flex; align-items: center; gap: 7px; }
  .row.muted { opacity: 0.65; }
  .divider { width: 1px; background: var(--border); margin: 4px 0; }
</style>
