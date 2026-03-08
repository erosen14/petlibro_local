const CARD_VERSION = '1.0.0';

const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const DAY_SHORT = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
const DAY_NUMBERS = [1, 2, 3, 4, 5, 6, 7];

class PetlibroFeedingCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._config = {};
    this._hass = null;
    this._editing = null;
    this._editData = {};
    this._quickSetupOpen = false;
    this._loading = false;

    // Event delegation - attached once, works across re-renders
    this.shadowRoot.addEventListener('click', this._handleClick.bind(this));
    this.shadowRoot.addEventListener('change', this._handleChange.bind(this));
  }

  static getConfigElement() {
    return document.createElement('petlibro-feeding-card-editor');
  }

  static getStubConfig() {
    return { entity: '' };
  }

  setConfig(config) {
    if (!config.entity) {
      throw new Error('Please define a feeding schedule entity');
    }
    this._config = { ...config };
    if (this._hass) this._render();
  }

  set hass(hass) {
    const oldHass = this._hass;
    this._hass = hass;

    // Don't re-render while user is editing
    if (this._editing !== null) return;

    if (!oldHass ||
        JSON.stringify(oldHass.states[this._config.entity]) !==
        JSON.stringify(hass.states[this._config.entity])) {
      this._render();
    }
  }

  get hass() { return this._hass; }

  _getState() {
    return this._hass?.states[this._config.entity];
  }

  _getPlans() {
    const state = this._getState();
    return state?.attributes?.plans || [];
  }

  _getDeviceId() {
    try {
      return this._hass.entities[this._config.entity]?.device_id;
    } catch {
      return null;
    }
  }

  async _callService(service, data = {}) {
    const deviceId = this._getDeviceId();
    try {
      await this._hass.callService('petlibro_local', service, data,
        deviceId ? { device_id: [deviceId] } : undefined);
    } catch (err) {
      console.error('Petlibro service error:', err);
      this._showToast(`Error: ${err.message || 'Service call failed'}`);
    }
  }

  _showToast(message) {
    const event = new CustomEvent('hass-notification', {
      bubbles: true,
      composed: true,
      detail: { message, duration: 4000 },
    });
    this.dispatchEvent(event);
  }

  _formatTime12h(time24) {
    if (!time24) return '';
    const [h, m] = time24.split(':').map(Number);
    const period = h >= 12 ? 'PM' : 'AM';
    const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
    return `${h12}:${String(m).padStart(2, '0')} ${period}`;
  }

  // ─── Rendering ───────────────────────────────────────────────

  _render() {
    const state = this._getState();
    const plans = this._getPlans();

    if (!state) {
      this.shadowRoot.innerHTML = `
        <ha-card>
          <div style="padding: 24px; text-align: center; color: var(--secondary-text-color);">
            Entity not found: ${this._config.entity}
          </div>
        </ha-card>`;
      return;
    }

    const nextFeed = state.state;
    const planCount = plans.length;

    // Calculate today's stats
    const todayJs = new Date().getDay(); // 0=Sun, 1=Mon
    const todayIso = todayJs === 0 ? 7 : todayJs; // ISO: 1=Mon, 7=Sun
    const todaysFeeds = plans.filter(p => {
      const days = p.days || [];
      return days.length === 0 || days.includes(todayIso);
    });
    const todayPortions = todaysFeeds.reduce((sum, p) => sum + (p.portions || 0), 0);

    this.shadowRoot.innerHTML = `
      ${this._styles()}
      <ha-card>
        ${this._renderHeader(nextFeed, planCount, todaysFeeds.length, todayPortions)}
        ${this._renderCalendar(plans)}
        <div class="divider"></div>
        ${this._renderSlots(plans)}
        ${this._renderQuickSetup()}
      </ha-card>
    `;
  }

  _renderHeader(nextFeed, planCount, todayFeeds, todayPortions) {
    const nextDisplay = nextFeed === 'No schedules' ? '\u2014' : nextFeed.replace('Next: ', '');
    return `
      <div class="header">
        <div class="header-left">
          <div class="header-icon">
            <svg viewBox="0 0 24 24" width="22" height="22">
              <path fill="currentColor" d="M11,9H9V2H7V9H5V2H3V9C3,11.12 4.66,12.84 6.75,12.97V22H9.25V12.97C11.34,12.84 13,11.12 13,9V2H11V9M16,6V14H18.5V22H21V2C18.24,2 16,4.24 16,7V6Z"/>
            </svg>
          </div>
          <div>
            <div class="header-title">${this._config.title || 'Feeding Schedule'}</div>
            <div class="header-sub">${planCount} plan${planCount !== 1 ? 's' : ''} configured</div>
          </div>
        </div>
        <div class="header-right">
          <div class="next-feed">${nextDisplay}</div>
          <div class="header-sub">${todayFeeds > 0
            ? `${todayFeeds} feed${todayFeeds > 1 ? 's' : ''} \u00b7 ${todayPortions}p today`
            : 'No feeds today'}</div>
        </div>
      </div>`;
  }

  // ─── Weekly Calendar ─────────────────────────────────────────

  _renderCalendar(plans) {
    if (plans.length === 0) {
      return `
        <div class="section">
          <div class="section-label">Weekly Overview</div>
          <div class="cal-empty">
            <svg viewBox="0 0 24 24" width="32" height="32" style="opacity:.35;margin-bottom:8px">
              <path fill="currentColor" d="M19,19H5V8H19M16,1V3H8V1H6V3H5C3.89,3 3,3.89 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5C21,3.89 20.1,3 19,3H18V1"/>
            </svg>
            <div>No feeding plans yet</div>
            <div style="font-size:12px;margin-top:4px;opacity:.7">Add a slot below or use Quick Setup</div>
          </div>
        </div>`;
    }

    const sorted = [...plans].sort((a, b) => (a.time_local || '').localeCompare(b.time_local || ''));

    let headerCells = `<div class="cal-corner"></div>`;
    DAY_LABELS.forEach(d => { headerCells += `<div class="cal-day-header">${d}</div>`; });
    headerCells += `<div class="cal-day-header"></div>`;

    let rows = '';
    sorted.forEach(plan => {
      const activeDays = plan.days && plan.days.length > 0 ? plan.days : [1,2,3,4,5,6,7];
      const displayTime = plan.time_display || this._formatTime12h(plan.time_local);

      rows += `<div class="cal-time">${displayTime}</div>`;
      DAY_NUMBERS.forEach(dayNum => {
        const active = activeDays.includes(dayNum);
        rows += `
          <div class="cal-cell">
            <div class="cal-dot ${active ? 'active' : 'inactive'}"
                 title="${active ? displayTime + ' - ' + plan.portions + ' portion(s)' : ''}">
              ${active ? plan.portions : ''}
            </div>
          </div>`;
      });
      rows += `<div class="cal-portions">${plan.portions}p</div>`;
    });

    return `
      <div class="section">
        <div class="section-label">Weekly Overview</div>
        <div class="cal-grid">
          ${headerCells}
          ${rows}
        </div>
      </div>`;
  }

  // ─── Slot List ───────────────────────────────────────────────

  _renderSlots(plans) {
    const planMap = {};
    plans.forEach(p => { planMap[p.slot] = p; });

    let slots = '';
    for (let i = 1; i <= 9; i++) {
      const plan = planMap[i];
      if (this._editing === i) {
        slots += this._renderSlotEditor(i, plan);
      } else if (plan) {
        slots += this._renderActiveSlot(i, plan);
      } else {
        slots += this._renderEmptySlot(i);
      }
    }

    return `
      <div class="section">
        <div class="section-label">Feeding Slots</div>
        <div class="slot-list">${slots}</div>
      </div>
      ${plans.length > 0 ? `
        <div class="clear-row">
          <button class="link-btn danger" data-action="clear-all">Remove all plans</button>
        </div>
      ` : ''}`;
  }

  _renderActiveSlot(slot, plan) {
    const activeDays = plan.days && plan.days.length > 0 ? plan.days : [1,2,3,4,5,6,7];
    const displayTime = plan.time_display || this._formatTime12h(plan.time_local);

    const dayBadges = DAY_SHORT.map((label, i) => {
      const active = activeDays.includes(i + 1);
      return `<span class="mini-day ${active ? 'on' : 'off'}">${label}</span>`;
    }).join('');

    return `
      <div class="slot-card">
        <div class="slot-view">
          <div class="slot-num">${slot}</div>
          <div class="slot-info">
            <div class="slot-main">
              <span class="slot-time">${displayTime}</span>
              <span class="dot-sep">\u00b7</span>
              <span>${plan.portions} portion${plan.portions !== 1 ? 's' : ''}</span>
              ${plan.audio ? '<span class="dot-sep">\u00b7</span><span class="audio-badge">&#x1f50a;</span>' : ''}
            </div>
            <div class="slot-days">${dayBadges}</div>
          </div>
          <div class="slot-btns">
            <button class="icon-btn" data-action="edit" data-slot="${slot}" title="Edit">
              <svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z"/></svg>
            </button>
            <button class="icon-btn del" data-action="delete" data-slot="${slot}" title="Delete">
              <svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z"/></svg>
            </button>
          </div>
        </div>
      </div>`;
  }

  _renderEmptySlot(slot) {
    return `
      <div class="slot-empty" data-action="add" data-slot="${slot}">
        <div class="slot-num empty">${slot}</div>
        <div class="slot-empty-label">Add feeding plan</div>
        <svg viewBox="0 0 24 24" width="16" height="16" style="margin-left:auto;opacity:.4">
          <path fill="currentColor" d="M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z"/>
        </svg>
      </div>`;
  }

  // ─── Slot Editor ─────────────────────────────────────────────

  _renderSlotEditor(slot, existingPlan) {
    const d = this._editData;
    const time = d.time || existingPlan?.time_local || '08:00';
    const portions = d.portions ?? existingPlan?.portions ?? 1;
    const days = d.days || (existingPlan?.days?.length > 0 ? [...existingPlan.days] : [1,2,3,4,5,6,7]);
    const audio = d.audio ?? existingPlan?.audio ?? true;

    const dayToggles = DAY_LABELS.map((label, i) => {
      const dayNum = i + 1;
      const active = days.includes(dayNum);
      return `<button class="day-btn ${active ? 'active' : ''}" data-action="toggle-day" data-day="${dayNum}">${DAY_SHORT[i]}</button>`;
    }).join('');

    return `
      <div class="slot-card editing">
        <div class="slot-editor-header">
          <div class="slot-num">${slot}</div>
          <span class="editor-title">${existingPlan ? 'Edit' : 'New'} Feeding Plan</span>
        </div>
        <div class="slot-editor-body">
          <!-- Time -->
          <div class="edit-field">
            <label class="edit-label">Time</label>
            <input type="time" class="time-input" id="edit-time" value="${time}">
          </div>

          <!-- Portions -->
          <div class="edit-field">
            <label class="edit-label">Portions</label>
            <div class="spinner">
              <button class="spin-btn" data-action="portions-dec">\u2212</button>
              <div class="spin-val" id="portions-val">${portions}</div>
              <button class="spin-btn" data-action="portions-inc">+</button>
            </div>
          </div>

          <!-- Days -->
          <div class="edit-field full">
            <label class="edit-label">Days</label>
            <div class="day-toggles">${dayToggles}</div>
            <div class="day-presets">
              <button class="preset-btn" data-action="days-all">Every day</button>
              <button class="preset-btn" data-action="days-weekdays">Weekdays</button>
              <button class="preset-btn" data-action="days-weekends">Weekends</button>
            </div>
          </div>

          <!-- Audio -->
          <div class="edit-field">
            <label class="edit-label">Audio</label>
            <button class="toggle-btn ${audio ? 'on' : ''}" data-action="toggle-audio">
              <div class="toggle-track"><div class="toggle-thumb"></div></div>
              <span class="toggle-text">${audio ? 'On' : 'Off'}</span>
            </button>
          </div>

          <!-- Actions -->
          <div class="edit-actions">
            <button class="btn secondary" data-action="cancel-edit">Cancel</button>
            <button class="btn primary" data-action="save-slot" data-slot="${slot}">Save</button>
          </div>
        </div>
      </div>`;
  }

  // ─── Quick Setup ─────────────────────────────────────────────

  _renderQuickSetup() {
    const chevron = this._quickSetupOpen ? 'open' : '';
    return `
      <div class="quick-section">
        <div class="quick-header" data-action="toggle-quick">
          <div class="quick-left">
            <svg viewBox="0 0 24 24" width="18" height="18" style="color:var(--plf-accent)">
              <path fill="currentColor" d="M11,15H13V17H11V15M11,7H13V13H11V7M12,2C6.47,2 2,6.5 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20Z"/>
            </svg>
            <span class="quick-title">Quick Setup</span>
          </div>
          <svg class="chevron ${chevron}" viewBox="0 0 24 24" width="20" height="20">
            <path fill="currentColor" d="M7.41,8.58L12,13.17L16.59,8.58L18,10L12,16L6,10L7.41,8.58Z"/>
          </svg>
        </div>
        <div class="quick-body ${this._quickSetupOpen ? 'open' : ''}">
          <div class="quick-grid">
            <div class="qfield">
              <label>Feed every</label>
              <select id="quick-interval">
                <option value="4">4 hours (6/day)</option>
                <option value="6">6 hours (4/day)</option>
                <option value="8" selected>8 hours (3/day)</option>
                <option value="12">12 hours (2/day)</option>
                <option value="24">Once a day</option>
              </select>
            </div>
            <div class="qfield">
              <label>Starting at</label>
              <select id="quick-start">
                <option value="06:00">6:00 AM</option>
                <option value="07:00">7:00 AM</option>
                <option value="08:00" selected>8:00 AM</option>
                <option value="09:00">9:00 AM</option>
                <option value="10:00">10:00 AM</option>
              </select>
            </div>
            <div class="qfield">
              <label>Portions</label>
              <select id="quick-portions">
                ${[1,2,3,4,5,6,7,8,9,10].map(n =>
                  `<option value="${n}" ${n===1?'selected':''}>${n}</option>`
                ).join('')}
              </select>
            </div>
            <div class="qfield">
              <label>Audio</label>
              <select id="quick-audio">
                <option value="true" selected>On</option>
                <option value="false">Off</option>
              </select>
            </div>
          </div>
          <div class="quick-footer">
            <span class="quick-warn">Replaces all existing plans</span>
            <button class="btn primary" data-action="apply-quick">Apply Schedule</button>
          </div>
        </div>
      </div>`;
  }

  // ─── Event Handlers ──────────────────────────────────────────

  _handleClick(e) {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.dataset.action;
    const slot = target.dataset.slot ? parseInt(target.dataset.slot, 10) : null;

    switch (action) {
      case 'edit':
      case 'add': {
        const plans = this._getPlans();
        const existing = plans.find(p => p.slot === slot);
        this._editing = slot;
        this._editData = existing ? {
          time: existing.time_local || '08:00',
          portions: existing.portions || 1,
          days: existing.days?.length > 0 ? [...existing.days] : [1,2,3,4,5,6,7],
          audio: existing.audio ?? true,
        } : {
          time: '08:00',
          portions: 1,
          days: [1,2,3,4,5,6,7],
          audio: true,
        };
        this._render();
        break;
      }

      case 'cancel-edit':
        this._editing = null;
        this._editData = {};
        this._render();
        break;

      case 'save-slot':
        this._saveSlot(slot);
        break;

      case 'delete':
        this._deleteSlot(slot);
        break;

      case 'toggle-day': {
        const day = parseInt(target.dataset.day, 10);
        const days = this._editData.days || [];
        const idx = days.indexOf(day);
        if (idx >= 0) {
          days.splice(idx, 1);
        } else {
          days.push(day);
          days.sort();
        }
        this._editData.days = days;
        this._render();
        break;
      }

      case 'days-all':
        this._editData.days = [1,2,3,4,5,6,7];
        this._render();
        break;

      case 'days-weekdays':
        this._editData.days = [1,2,3,4,5];
        this._render();
        break;

      case 'days-weekends':
        this._editData.days = [6,7];
        this._render();
        break;

      case 'toggle-audio':
        this._editData.audio = !this._editData.audio;
        this._render();
        break;

      case 'portions-inc': {
        const cur = this._editData.portions || 1;
        if (cur < 20) {
          this._editData.portions = cur + 1;
          const display = this.shadowRoot.querySelector('#portions-val');
          if (display) display.textContent = this._editData.portions;
        }
        break;
      }

      case 'portions-dec': {
        const cur = this._editData.portions || 1;
        if (cur > 1) {
          this._editData.portions = cur - 1;
          const display = this.shadowRoot.querySelector('#portions-val');
          if (display) display.textContent = this._editData.portions;
        }
        break;
      }

      case 'toggle-quick':
        this._quickSetupOpen = !this._quickSetupOpen;
        this._render();
        break;

      case 'apply-quick':
        this._applyQuickSetup();
        break;

      case 'clear-all':
        this._confirmClearAll();
        break;
    }
  }

  _handleChange(e) {
    if (e.target.id === 'edit-time') {
      this._editData.time = e.target.value;
    }
  }

  // ─── Service Callers ─────────────────────────────────────────

  async _saveSlot(slot) {
    // Read latest time value from input
    const timeInput = this.shadowRoot.querySelector('#edit-time');
    if (timeInput) this._editData.time = timeInput.value;

    const { time, portions, days, audio } = this._editData;
    if (!time) {
      this._showToast('Please select a feeding time');
      return;
    }

    if (!days || days.length === 0) {
      this._showToast('Please select at least one day');
      return;
    }

    this._editing = null;
    this._editData = {};
    this._render();

    await this._callService('set_feeding_plan', {
      plan_id: slot,
      time: time,
      portions: portions || 1,
      days: days.length === 7 ? [] : days.map(String),
      enable_audio: audio ?? true,
    });
  }

  async _deleteSlot(slot) {
    await this._callService('remove_feeding_plan', { plan_id: slot });
  }

  async _applyQuickSetup() {
    const root = this.shadowRoot;
    const interval = parseInt(root.querySelector('#quick-interval')?.value || '8', 10);
    const startTime = root.querySelector('#quick-start')?.value || '08:00';
    const portions = parseInt(root.querySelector('#quick-portions')?.value || '1', 10);
    const audio = root.querySelector('#quick-audio')?.value === 'true';

    // Clear first
    await this._callService('clear_feeding_plans', {});

    // Create evenly-spaced plans
    const [startH] = startTime.split(':').map(Number);
    let planId = 1;
    let hour = startH;
    while (hour < 24 && planId <= 9) {
      await this._callService('set_feeding_plan', {
        plan_id: planId,
        time: `${String(hour).padStart(2, '0')}:00`,
        portions,
        days: [],
        enable_audio: audio,
      });
      planId++;
      hour += interval;
    }

    this._quickSetupOpen = false;
    this._showToast(`Created ${planId - 1} feeding plan(s)`);
  }

  _confirmClearAll() {
    // Simple confirmation
    const dialog = document.createElement('div');
    dialog.innerHTML = '';
    if (confirm('Remove all feeding plans? This cannot be undone.')) {
      this._clearAll();
    }
  }

  async _clearAll() {
    await this._callService('clear_feeding_plans', {});
  }

  getCardSize() {
    const plans = this._getPlans();
    return Math.max(4, 3 + plans.length + 2);
  }

  // ─── Styles ──────────────────────────────────────────────────

  _styles() {
    return `<style>
      :host {
        --plf-primary: var(--primary-color, #03a9f4);
        --plf-accent: var(--accent-color, #ff9800);
        --plf-bg: var(--card-background-color, #fff);
        --plf-text: var(--primary-text-color, #212121);
        --plf-text2: var(--secondary-text-color, #727272);
        --plf-divider: var(--divider-color, #e0e0e0);
        --plf-surface: var(--secondary-background-color, #f5f5f5);
        --plf-radius: 12px;
      }
      ha-card { padding: 0; overflow: hidden; }

      /* ── Header ── */
      .header {
        padding: 20px 20px 16px;
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 12px;
      }
      .header-left {
        display: flex;
        align-items: center;
        gap: 12px;
      }
      .header-icon {
        width: 42px; height: 42px;
        border-radius: 12px;
        background: var(--plf-primary);
        display: flex; align-items: center; justify-content: center;
        color: white; flex-shrink: 0;
      }
      .header-title {
        font-size: 16px;
        font-weight: 600;
        color: var(--plf-text);
      }
      .header-sub {
        font-size: 12px;
        color: var(--plf-text2);
        margin-top: 1px;
      }
      .header-right { text-align: right; flex-shrink: 0; }
      .next-feed {
        font-size: 15px;
        font-weight: 700;
        color: var(--plf-primary);
      }

      /* ── Section ── */
      .section { padding: 0 20px 16px; }
      .section-label {
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        color: var(--plf-text2);
        margin-bottom: 10px;
        padding-top: 4px;
      }
      .divider {
        height: 1px;
        background: var(--plf-divider);
        margin: 0 20px 4px;
      }

      /* ── Calendar ── */
      .cal-grid {
        display: grid;
        grid-template-columns: 72px repeat(7, 1fr) 28px;
        gap: 3px 0;
        align-items: center;
      }
      .cal-corner { }
      .cal-day-header {
        font-size: 11px;
        font-weight: 700;
        color: var(--plf-text2);
        text-align: center;
        padding-bottom: 6px;
      }
      .cal-time {
        font-size: 12px;
        font-weight: 500;
        color: var(--plf-text);
        text-align: right;
        padding-right: 10px;
        white-space: nowrap;
      }
      .cal-cell {
        display: flex;
        justify-content: center;
        padding: 4px 0;
      }
      .cal-dot {
        width: 26px; height: 26px;
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 10px; font-weight: 700;
        transition: transform 0.15s;
      }
      .cal-dot.active {
        background: var(--plf-primary);
        color: white;
      }
      .cal-dot.active:hover { transform: scale(1.15); }
      .cal-dot.inactive {
        border: 2px solid var(--plf-divider);
        color: transparent;
        width: 22px; height: 22px;
      }
      .cal-portions {
        font-size: 10px;
        font-weight: 600;
        color: var(--plf-text2);
        padding-left: 4px;
        white-space: nowrap;
      }
      .cal-empty {
        text-align: center;
        padding: 28px 20px;
        color: var(--plf-text2);
        font-size: 14px;
        background: var(--plf-surface);
        border-radius: 10px;
        display: flex;
        flex-direction: column;
        align-items: center;
      }

      /* ── Slot List ── */
      .slot-list {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }

      /* Active slot */
      .slot-card {
        border: 1px solid var(--plf-divider);
        border-radius: 10px;
        overflow: hidden;
        transition: box-shadow 0.2s, border-color 0.2s;
      }
      .slot-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
      .slot-card.editing {
        border-color: var(--plf-primary);
        box-shadow: 0 0 0 1px var(--plf-primary);
      }
      .slot-view {
        padding: 10px 12px;
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .slot-num {
        width: 28px; height: 28px;
        border-radius: 50%;
        background: var(--plf-primary);
        color: white;
        display: flex; align-items: center; justify-content: center;
        font-size: 12px; font-weight: 700;
        flex-shrink: 0;
      }
      .slot-num.empty {
        background: transparent;
        border: 2px dashed var(--plf-divider);
        color: var(--plf-text2);
      }
      .slot-info { flex: 1; min-width: 0; }
      .slot-main {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 14px;
        font-weight: 500;
        color: var(--plf-text);
        flex-wrap: wrap;
      }
      .slot-time { font-weight: 600; }
      .dot-sep { color: var(--plf-divider); }
      .audio-badge { font-size: 12px; }
      .slot-days {
        margin-top: 3px;
        display: flex;
        gap: 2px;
      }
      .mini-day {
        font-size: 9px;
        font-weight: 700;
        width: 18px; height: 16px;
        border-radius: 3px;
        display: inline-flex;
        align-items: center; justify-content: center;
      }
      .mini-day.on {
        background: color-mix(in srgb, var(--plf-primary) 15%, transparent);
        color: var(--plf-primary);
      }
      .mini-day.off { color: var(--plf-divider); }
      .slot-btns {
        display: flex;
        gap: 2px;
        flex-shrink: 0;
      }
      .icon-btn {
        width: 32px; height: 32px;
        border: none;
        background: transparent;
        border-radius: 50%;
        cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        color: var(--plf-text2);
        transition: background 0.15s, color 0.15s;
        padding: 0;
      }
      .icon-btn:hover {
        background: var(--plf-surface);
        color: var(--plf-text);
      }
      .icon-btn.del:hover {
        background: #ffebee;
        color: #c62828;
      }

      /* Empty slot */
      .slot-empty {
        padding: 8px 12px;
        display: flex;
        align-items: center;
        gap: 10px;
        cursor: pointer;
        border: 1px dashed var(--plf-divider);
        border-radius: 10px;
        transition: background 0.15s, border-color 0.15s;
      }
      .slot-empty:hover {
        background: var(--plf-surface);
        border-color: var(--plf-primary);
      }
      .slot-empty-label {
        font-size: 13px;
        color: var(--plf-text2);
      }

      /* ── Editor ── */
      .slot-editor-header {
        padding: 10px 14px;
        display: flex;
        align-items: center;
        gap: 10px;
        border-bottom: 1px solid var(--plf-divider);
      }
      .editor-title {
        font-size: 14px;
        font-weight: 500;
        color: var(--plf-text);
      }
      .slot-editor-body {
        padding: 16px;
        background: var(--plf-surface);
        display: flex;
        flex-direction: column;
        gap: 14px;
      }
      .edit-field {
        display: flex;
        align-items: center;
        gap: 12px;
      }
      .edit-field.full {
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
      }
      .edit-label {
        font-size: 13px;
        font-weight: 600;
        color: var(--plf-text2);
        min-width: 64px;
      }

      /* Time input */
      .time-input {
        font-size: 15px;
        padding: 8px 12px;
        border: 1px solid var(--plf-divider);
        border-radius: 8px;
        background: var(--plf-bg);
        color: var(--plf-text);
        outline: none;
        font-family: inherit;
      }
      .time-input:focus {
        border-color: var(--plf-primary);
        box-shadow: 0 0 0 2px color-mix(in srgb, var(--plf-primary) 20%, transparent);
      }

      /* Spinner */
      .spinner {
        display: flex;
        align-items: center;
        border: 1px solid var(--plf-divider);
        border-radius: 8px;
        overflow: hidden;
        background: var(--plf-bg);
      }
      .spin-btn {
        width: 36px; height: 36px;
        border: none; background: transparent;
        cursor: pointer;
        font-size: 18px; font-weight: 600;
        color: var(--plf-primary);
        display: flex; align-items: center; justify-content: center;
        transition: background 0.1s;
        padding: 0;
      }
      .spin-btn:hover { background: var(--plf-surface); }
      .spin-btn:active { background: var(--plf-divider); }
      .spin-val {
        width: 40px;
        text-align: center;
        font-size: 15px;
        font-weight: 700;
        color: var(--plf-text);
        border-left: 1px solid var(--plf-divider);
        border-right: 1px solid var(--plf-divider);
        height: 36px;
        line-height: 36px;
      }

      /* Day toggles */
      .day-toggles {
        display: flex;
        gap: 6px;
      }
      .day-btn {
        width: 36px; height: 36px;
        border-radius: 50%;
        border: 2px solid var(--plf-divider);
        background: transparent;
        cursor: pointer;
        font-size: 12px; font-weight: 700;
        color: var(--plf-text2);
        display: flex; align-items: center; justify-content: center;
        transition: all 0.15s;
        padding: 0;
      }
      .day-btn.active {
        background: var(--plf-primary);
        border-color: var(--plf-primary);
        color: white;
      }
      .day-btn:hover:not(.active) {
        border-color: var(--plf-primary);
        color: var(--plf-primary);
      }

      /* Day presets */
      .day-presets {
        display: flex;
        gap: 6px;
      }
      .preset-btn {
        font-size: 11px;
        padding: 4px 10px;
        border: 1px solid var(--plf-divider);
        border-radius: 12px;
        background: var(--plf-bg);
        color: var(--plf-text2);
        cursor: pointer;
        transition: all 0.15s;
      }
      .preset-btn:hover {
        border-color: var(--plf-primary);
        color: var(--plf-primary);
      }

      /* Toggle */
      .toggle-btn {
        display: flex;
        align-items: center;
        gap: 8px;
        background: none;
        border: none;
        cursor: pointer;
        padding: 4px;
      }
      .toggle-track {
        width: 44px; height: 24px;
        border-radius: 12px;
        background: var(--plf-divider);
        position: relative;
        transition: background 0.2s;
      }
      .toggle-btn.on .toggle-track { background: var(--plf-primary); }
      .toggle-thumb {
        width: 20px; height: 20px;
        border-radius: 50%;
        background: white;
        position: absolute;
        top: 2px; left: 2px;
        transition: transform 0.2s;
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
      }
      .toggle-btn.on .toggle-thumb { transform: translateX(20px); }
      .toggle-text {
        font-size: 13px;
        color: var(--plf-text2);
        font-weight: 500;
      }

      /* Buttons */
      .edit-actions {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        padding-top: 4px;
      }
      .btn {
        padding: 9px 22px;
        border: none;
        border-radius: 8px;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: all 0.15s;
        font-family: inherit;
      }
      .btn.primary {
        background: var(--plf-primary);
        color: white;
      }
      .btn.primary:hover { filter: brightness(1.1); }
      .btn.secondary {
        background: transparent;
        color: var(--plf-text2);
        border: 1px solid var(--plf-divider);
      }
      .btn.secondary:hover { background: var(--plf-surface); }

      /* Clear all */
      .clear-row {
        padding: 4px 20px 16px;
        display: flex;
        justify-content: center;
      }
      .link-btn {
        font-size: 12px;
        background: none;
        border: none;
        cursor: pointer;
        padding: 4px 12px;
        border-radius: 6px;
        transition: all 0.15s;
        font-family: inherit;
        color: var(--plf-text2);
      }
      .link-btn.danger:hover {
        color: #c62828;
        background: #ffebee;
      }

      /* ── Quick Setup ── */
      .quick-section {
        border-top: 1px solid var(--plf-divider);
      }
      .quick-header {
        padding: 14px 20px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        cursor: pointer;
        user-select: none;
        transition: background 0.15s;
      }
      .quick-header:hover { background: var(--plf-surface); }
      .quick-left {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .quick-title {
        font-size: 13px;
        font-weight: 600;
        color: var(--plf-text);
      }
      .chevron {
        transition: transform 0.2s;
        color: var(--plf-text2);
      }
      .chevron.open { transform: rotate(180deg); }
      .quick-body {
        padding: 0 20px 16px;
        display: none;
      }
      .quick-body.open { display: block; }
      .quick-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
      }
      .qfield {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .qfield label {
        font-size: 11px;
        font-weight: 600;
        color: var(--plf-text2);
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .qfield select {
        padding: 8px 10px;
        border: 1px solid var(--plf-divider);
        border-radius: 8px;
        background: var(--plf-bg);
        color: var(--plf-text);
        font-size: 13px;
        font-family: inherit;
        outline: none;
        cursor: pointer;
      }
      .qfield select:focus { border-color: var(--plf-primary); }
      .quick-footer {
        margin-top: 14px;
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .quick-warn {
        font-size: 11px;
        color: var(--plf-accent);
        font-weight: 500;
      }

      /* ── Responsive ── */
      @media (max-width: 400px) {
        .header { padding: 16px; }
        .section { padding: 0 16px 12px; }
        .divider { margin: 0 16px 4px; }
        .cal-grid { grid-template-columns: 60px repeat(7, 1fr) 24px; }
        .cal-dot { width: 22px; height: 22px; }
        .cal-dot.inactive { width: 18px; height: 18px; }
        .day-btn { width: 32px; height: 32px; font-size: 11px; }
        .day-toggles { gap: 4px; }
        .quick-grid { grid-template-columns: 1fr; }
      }
    </style>`;
  }
}


// ─── Card Editor ─────────────────────────────────────────────────

class PetlibroFeedingCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass) return;

    const entities = Object.keys(this._hass.states)
      .filter(eid => eid.includes('feeding_schedule'))
      .sort();

    this.shadowRoot.innerHTML = `
      <style>
        .editor { padding: 16px; }
        .field { margin-bottom: 16px; }
        label { display: block; font-weight: 500; margin-bottom: 6px; font-size: 14px; color: var(--primary-text-color); }
        select, input {
          width: 100%;
          padding: 10px 12px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          font-size: 14px;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
          font-family: inherit;
          outline: none;
          box-sizing: border-box;
        }
        select:focus, input:focus { border-color: var(--primary-color); }
        .hint { font-size: 12px; color: var(--secondary-text-color); margin-top: 6px; }
      </style>
      <div class="editor">
        <div class="field">
          <label>Feeding Schedule Entity</label>
          <select id="entity">
            <option value="">Select entity...</option>
            ${entities.map(eid =>
              `<option value="${eid}" ${eid === this._config?.entity ? 'selected' : ''}>
                ${this._hass.states[eid]?.attributes?.friendly_name || eid}
              </option>`
            ).join('')}
          </select>
          <div class="hint">Select your Petlibro feeding schedule sensor</div>
        </div>
        <div class="field">
          <label>Card Title (optional)</label>
          <input type="text" id="title" value="${this._config?.title || ''}" placeholder="Feeding Schedule">
          <div class="hint">Custom title for the card header</div>
        </div>
      </div>
    `;

    this.shadowRoot.querySelector('#entity')?.addEventListener('change', (e) => {
      this._config = { ...this._config, entity: e.target.value };
      this._fireChanged();
    });

    this.shadowRoot.querySelector('#title')?.addEventListener('input', (e) => {
      this._config = { ...this._config, title: e.target.value };
      this._fireChanged();
    });
  }

  _fireChanged() {
    this.dispatchEvent(new CustomEvent('config-changed', {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    }));
  }
}


// ─── Register ────────────────────────────────────────────────────

customElements.define('petlibro-feeding-card', PetlibroFeedingCard);
customElements.define('petlibro-feeding-card-editor', PetlibroFeedingCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'petlibro-feeding-card',
  name: 'Petlibro Feeding Schedule',
  description: 'View and manage your Petlibro feeder\'s feeding schedule with a weekly calendar view.',
  preview: true,
  documentationURL: 'https://github.com/erosen14/petlibro_local',
});

console.info(
  `%c PETLIBRO-FEEDING-CARD %c v${CARD_VERSION} `,
  'color: white; background: #03a9f4; font-weight: 700; padding: 2px 8px; border-radius: 4px 0 0 4px;',
  'color: #03a9f4; background: #e3f2fd; font-weight: 700; padding: 2px 8px; border-radius: 0 4px 4px 0;',
);
