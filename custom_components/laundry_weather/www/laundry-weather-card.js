/**
 * Laundry Weather Card
 *
 * Shows where washing will dry fastest right now, when to move it out, when to
 * bring it in, and how the next day looks.
 *
 * Everything is read from the attributes of one entity — the recommendation
 * sensor — so a dashboard takes a single `entity:` and survives a room being
 * renamed or added.
 *
 * Accessibility note that is load-bearing rather than decorative: the owner is
 * colour-blind (green/yellow/red/brown), so nothing here encodes meaning in
 * hue. Drying bands are a fill meter plus the word, and the forecast chart
 * separates its three series by dash pattern, marker shape and a direct label,
 * each of which works on its own.
 */

var CARD_VERSION = "0.3.1";

var STATIC_BASE = "/laundry_weather_static";

var HEADLINE = {
  good: "It Is a Good Day to Dry",
  bad: "It Is Not a Good Day to Dry",
};

// Constructed Klingon, not canon — see the README.
var HEADLINE_KLINGON = {
  good: "QaDmoHlu'meH QaQ jajvam",
  bad: "QaDmoHlu'meH QaQbe' jajvam",
};

var BUNDLED_IMAGE = {
  good: STATIC_BASE + "/worf-good.png",
  bad: STATIC_BASE + "/worf-bad.png",
  goodKlingon: STATIC_BASE + "/worf-good-klingon.png",
  badKlingon: STATIC_BASE + "/worf-bad-klingon.png",
};

var DEFAULTS = {
  title: "",
  show_mascot: true,
  show_spots: true,
  show_timing: true,
  show_forecast: true,
  show_switch: true,
  forecast_hours: 24,
  klingon: null,
  compact: false,
  // "auto" follows Home Assistant; "12" and "24" override it.
  time_format: "auto",
  image_good: "",
  image_bad: "",
};

function _lwEscape(text) {
  var el = document.createElement("span");
  el.textContent = text === null || text === undefined ? "" : String(text);
  return el.innerHTML;
}

/**
 * Time formatting follows Home Assistant, not the browser.
 *
 * Both parts of that matter. Formatting in the browser's own zone showed
 * 08:49 in the footer beside a chart starting at 19:00 — the same instant,
 * rendered two different ways, because the browser was on UTC and the home was
 * not. And the 12/24-hour choice is a Home Assistant setting, so taking the
 * browser default put "02:00 AM" in the timings above a chart labelled 19:00.
 */
function _lwFormatters(hass, override) {
  var locale = (hass && hass.locale && hass.locale.language) || navigator.language;
  var zone = (hass && hass.config && hass.config.time_zone) || undefined;
  // The card's own setting wins; "auto" defers to Home Assistant. Worth having
  // because a locale like en-GB defaults to 24-hour and there is otherwise no
  // way to ask this card for 12 without changing it for the whole frontend.
  var format = (override && override !== "auto")
    ? override
    : (hass && hass.locale && hass.locale.time_format);
  var hour12;
  if (format === "12") { hour12 = true; }
  else if (format === "24") { hour12 = false; }
  // "language" and "system" both mean "let the locale decide".

  // "2-digit" hours read naturally on a 24-hour clock ("05:54") and wrong on
  // a 12-hour one, where nobody writes "05:54 PM".
  var options = {
    hour: hour12 ? "numeric" : "2-digit",
    minute: "2-digit",
    timeZone: zone,
  };
  if (hour12 !== undefined) { options.hour12 = hour12; }
  // The chart axis gets its own, shorter format. A 12-hour "08:00 PM" is
  // nearly twice the width of "20:00", and using the full format there
  // collided the hour labels into an unreadable smear at 380px.
  var axisOptions = { hour: "numeric", timeZone: zone };
  if (hour12 !== undefined) { axisOptions.hour12 = hour12; }

  return {
    time: new Intl.DateTimeFormat(locale, options),
    axis: new Intl.DateTimeFormat(locale, axisOptions),
    day: new Intl.DateTimeFormat(locale, { weekday: "short", timeZone: zone }),
    hour12: hour12,
  };
}

function _lwTime(iso, fmt) {
  if (!iso) { return ""; }
  var when = new Date(iso);
  if (isNaN(when.getTime())) { return ""; }
  return fmt.time.format(when);
}

/** Hour only, for the chart axis. */
function _lwHour(iso, fmt) {
  if (!iso) { return ""; }
  var when = new Date(iso);
  if (isNaN(when.getTime())) { return ""; }
  return fmt.axis.format(when).replace(/\s+/g, "\u2009");
}

/** "Sun 11:00 AM-4:00 PM (peak 16.6)", in the viewer's own clock format.
 *
 * Composed here rather than read from the sensor's `text` because whether a
 * clock reads 16:00 or 4:00 PM is `hass.locale.time_format` — a per-user
 * frontend setting that never reaches the integration.
 */
function _lwWindowText(window, fmt) {
  if (!window || !window.start || !window.end) { return ""; }
  var start = new Date(window.start);
  var end = new Date(window.end);
  if (isNaN(start.getTime()) || isNaN(end.getTime())) { return ""; }
  var startDay = fmt.day.format(start);
  var endDay = fmt.day.format(end);
  // The horizon is 48 hours, so the window is regularly tomorrow. Dropping the
  // day would be actively misleading; naming it twice only when it changes.
  var tail = fmt.time.format(end);
  if (endDay !== startDay) { tail = endDay + " " + tail; }
  var text = startDay + " " + fmt.time.format(start) + "-" + tail;
  if (window.peak !== undefined && window.peak !== null) {
    text += " (peak " + window.peak + ")";
  }
  return text;
}

/** Fill {move_at} / {bring_by} / {window} in the advice sentence. */
function _lwAdvice(attrs, fmt) {
  var template = attrs.advice_template;
  if (!template) { return attrs.advice || ""; }
  var timings = attrs.timings || {};
  return template
    .split("{move_at}").join(_lwTime(timings.move_outside_at, fmt))
    .split("{bring_by}").join(_lwTime(timings.bring_in_by, fmt))
    .split("{window}").join(_lwWindowText(timings.best_window, fmt));
}

/** "— in 35 min" / "— in 2.3 h" / "— Sun 07:15" / "(already past)". */
function _lwCountdown(iso, fmt) {
  if (!iso) { return ""; }
  var then = new Date(iso);
  if (isNaN(then.getTime())) { return ""; }
  var minutes = (then.getTime() - Date.now()) / 60000;
  if (minutes < 0) { return "(already past)"; }
  if (minutes < 60) { return "— in " + Math.round(minutes) + " min"; }
  if (minutes < 24 * 60) { return "— in " + (minutes / 60).toFixed(1) + " h"; }
  return "— " + fmt.day.format(then) + " " + _lwTime(iso, fmt);
}

class LaundryWeatherCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = Object.assign({}, DEFAULTS);
    this._hass = null;
    this._lastDataJSON = "";
    this._formatters = null;
    this._tick = null;
  }

  static getConfigElement() {
    return document.createElement("laundry-weather-card-editor");
  }

  static getStubConfig(hass) {
    var found = "";
    if (hass && hass.states) {
      found = Object.keys(hass.states).find(function (id) {
        return id.indexOf("sensor.") === 0 &&
          hass.states[id].attributes &&
          hass.states[id].attributes.spots !== undefined;
      }) || "";
    }
    return { type: "custom:laundry-weather-card", entity: found };
  }

  setConfig(config) {
    if (!config || !config.entity) {
      throw new Error("Pick the Laundry Weather recommendation sensor.");
    }
    this._config = Object.assign({}, DEFAULTS, config);
    this._lastDataJSON = "";
    this._formatters = null;
    if (this._hass) { this._render(); }
  }

  set hass(hass) {
    this._hass = hass;
    this._formatters = null;
    var json = this._dataJSON();
    if (json !== this._lastDataJSON) {
      this._lastDataJSON = json;
      this._render();
    }
  }

  getCardSize() {
    var size = 3;
    if (this._config.show_mascot) { size += 3; }
    if (this._config.show_spots) { size += 2; }
    if (this._config.show_timing) { size += 2; }
    if (this._config.show_forecast) { size += 3; }
    return size;
  }

  connectedCallback() {
    // Only the countdown text is rewritten on this tick — re-rendering the
    // whole card every minute would restart the image fetch and lose focus.
    var self = this;
    this._tick = setInterval(function () { self._refreshCountdowns(); }, 60000);
  }

  disconnectedCallback() {
    if (this._tick) { clearInterval(this._tick); this._tick = null; }
  }

  _state() {
    if (!this._hass) { return null; }
    return this._hass.states[this._config.entity] || null;
  }

  _dataJSON() {
    var state = this._state();
    if (!state) { return ""; }
    return JSON.stringify([state.state, state.attributes]);
  }

  _fmt() {
    if (!this._formatters) {
      this._formatters = _lwFormatters(this._hass, this._config.time_format);
    }
    return this._formatters;
  }

  _klingon(attrs) {
    if (this._config.klingon === true || this._config.klingon === false) {
      return this._config.klingon;
    }
    return !!(attrs.config && attrs.config.klingon);
  }

  _refreshCountdowns() {
    if (!this.shadowRoot) { return; }
    var fmt = this._fmt();
    var nodes = this.shadowRoot.querySelectorAll(".cd[data-at]");
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].textContent = _lwCountdown(nodes[i].getAttribute("data-at"), fmt);
    }
  }

  // --- pieces ------------------------------------------------------------

  _banner(attrs, good, klingon) {
    if (!this._config.show_mascot) { return ""; }

    var custom = good ? this._config.image_good : this._config.image_bad;
    var headline = (klingon ? HEADLINE_KLINGON : HEADLINE)[good ? "good" : "bad"];
    var plain = HEADLINE[good ? "good" : "bad"];
    var src;
    var caption = "";

    if (custom) {
      src = custom;
      // A supplied picture has no Klingon variant baked in, so the Klingon
      // goes underneath rather than being faked over somebody else's artwork.
      if (klingon) {
        caption = '<div class="caption">' + _lwEscape(headline) + "</div>";
      }
    } else {
      src = klingon
        ? BUNDLED_IMAGE[good ? "goodKlingon" : "badKlingon"]
        : BUNDLED_IMAGE[good ? "good" : "bad"];
    }

    // The verdict lives in the alt text: the artwork carries it visually, and
    // this is what a screen reader announces and what shows if the image
    // cannot be loaded.
    return '<div class="banner">' +
      '<img src="' + _lwEscape(src) + '" alt="' + _lwEscape(plain) + '" ' +
      'loading="lazy" decoding="async">' + caption + "</div>";
  }

  _summary(state, attrs) {
    var band = attrs.recommended_band || "";
    var score = attrs.recommended_score;
    var bits = [state.state, band];
    if (score !== undefined && score !== null) { bits.push(String(score)); }
    return '<div class="sub">' + _lwEscape(bits.filter(Boolean).join(" · ")) +
      "</div>";
  }

  _spots(attrs) {
    if (!this._config.show_spots || !attrs.spots || !attrs.spots.length) {
      return "";
    }
    var rows = attrs.spots.map(function (spot, index) {
      return '<tr class="' + (index === 0 ? "best" : "") + '">' +
        '<td><span class="marks" aria-hidden="true">' + _lwEscape(spot.marks) +
        "</span>" + _lwEscape(spot.name) + "</td>" +
        "<td>" + _lwEscape(spot.band) + "</td>" +
        '<td class="num">' + _lwEscape(spot.score) + "</td></tr>";
    }).join("");

    return '<table class="spots"><thead><tr>' +
      "<th>Where to hang it</th><th>Drying</th>" +
      '<th class="num">Score</th></tr></thead><tbody>' + rows +
      "</tbody></table>";
  }

  _timing(attrs) {
    if (!this._config.show_timing || !attrs.timings) { return ""; }
    var fmt = this._fmt();
    var timings = attrs.timings;
    var overnight = attrs.overnight || {};
    var rows = [];

    // Nothing drying means there is no deadline. Showing a countdown here once
    // told the user they had 52 minutes, four hours after sunset.
    var notDrying = timings.bring_in_source === "not_drying";

    rows.push(this._timingRow(
      "Move outside",
      timings.move_outside_at
        ? _lwEscape(_lwTime(timings.move_outside_at, fmt)) +
          ' <em class="cd" data-at="' + _lwEscape(timings.move_outside_at) +
          '">' + _lwEscape(_lwCountdown(timings.move_outside_at, fmt)) + "</em>"
        : "Not worth it today"
    ));

    if (notDrying) {
      rows.push(this._timingRow("Bring in by", "Not drying now"));
    } else if (timings.bring_in_by) {
      rows.push(this._timingRow(
        "Bring in by",
        _lwEscape(_lwTime(timings.bring_in_by, fmt)) +
        ' <em class="cd" data-at="' + _lwEscape(timings.bring_in_by) + '">' +
        _lwEscape(_lwCountdown(timings.bring_in_by, fmt)) + "</em>"
      ));
    }

    var windowText = _lwWindowText(timings.best_window, fmt);
    if (windowText) {
      rows.push(this._timingRow("Best window", _lwEscape(windowText)));
    }

    if (overnight.rewet !== undefined && overnight.rewet !== null) {
      // Filled/empty marker plus the word — never the colour alone.
      var dew = overnight.rewet
        ? "● Yes — down to " + _lwEscape(overnight.min_temp) + " °C"
        : "○ No";
      rows.push(this._timingRow("Dew overnight", dew));
    }

    return '<dl class="timing">' + rows.join("") + "</dl>";
  }

  _timingRow(label, value) {
    return '<div class="trow"><dt>' + _lwEscape(label) + "</dt><dd>" + value +
      "</dd></div>";
  }

  _forecast(attrs) {
    if (!this._config.show_forecast) { return ""; }
    var series = (attrs.forecast || []).slice(
      0, Math.max(1, this._config.forecast_hours)
    );
    var meta = attrs.forecast_meta || {};

    if (series.length < 6) {
      return '<div class="strip"><h4>Drying forecast</h4>' +
        '<p class="empty">Not enough hourly forecast yet. Check that the ' +
        "weather entity you picked provides an hourly forecast — daily-only " +
        "providers cannot fill this in.</p></div>";
    }

    var indoor = attrs.best_indoor_score;
    var indoorName = attrs.best_indoor_room || "Indoors";
    var note = "";
    if (meta.sun_model && meta.sun_model !== "uv") {
      note = '<p class="note">Your forecast provides no UV index, so sunshine ' +
        "is estimated from cloud cover.</p>";
    }
    if (meta.stale) {
      note += '<p class="note">Showing the last forecast that loaded.</p>';
    }

    return '<div class="strip"><h4>Drying forecast — next ' + series.length +
      " hours</h4>" + this._legend(indoorName) +
      this._chart(series, indoor, indoorName) + note + "</div>";
  }

  _legend(indoorName) {
    return '<div class="legend">' +
      '<span><svg width="22" height="8" aria-hidden="true">' +
      '<line x1="1" y1="4" x2="21" y2="4" stroke="currentColor" stroke-width="2"/>' +
      '<circle cx="11" cy="4" r="2.4" fill="currentColor"/></svg>Under cover</span>' +
      '<span><svg width="22" height="8" aria-hidden="true">' +
      '<line x1="1" y1="4" x2="21" y2="4" stroke="currentColor" stroke-width="2" stroke-dasharray="5 3"/>' +
      '<path d="M11 1.4 L13.4 4 L11 6.6 L8.6 4 Z" fill="none" stroke="currentColor" stroke-width="1.2"/>' +
      "</svg>In the sun</span>" +
      '<span><svg width="22" height="8" aria-hidden="true">' +
      '<line x1="1" y1="4" x2="21" y2="4" stroke="currentColor" stroke-width="1.4" stroke-dasharray="1 2" opacity=".65"/>' +
      "</svg>" + _lwEscape(indoorName) + "</span>" +
      '<span><svg width="16" height="8" aria-hidden="true">' +
      '<rect x="0" y="1" width="16" height="6" fill="none" stroke="currentColor" stroke-width="1"/>' +
      '<path d="M0 7 L6 1 M5 7 L11 1 M10 7 L16 1" stroke="currentColor" stroke-width="1"/>' +
      "</svg>Rain likely</span></div>";
  }

  /**
   * The forecast chart.
   *
   * Sized so it stays legible at a 380px card with no horizontal scroll: the
   * viewBox is 340 units wide, which lands at roughly 1:1 once the card's
   * padding is taken off, so 8.5-unit text renders at about 8.5px.
   */
  _chart(series, indoor, indoorName) {
    var W = 340, H = 168, L = 30, R = 286, T = 10, B = 132;
    var n = series.length;
    var uid = "lw" + Math.abs(this._config.entity.split("").reduce(
      function (a, c) { return ((a << 5) - a + c.charCodeAt(0)) | 0; }, 0
    ));

    var values = [];
    series.forEach(function (h) { values.push(h.sun, h.cov); });
    if (typeof indoor === "number") { values.push(indoor); }
    var yMax = Math.max(13.2, Math.ceil(Math.max.apply(null, values) * 1.1));

    var x = function (i) { return L + (R - L) * (n === 1 ? 0.5 : i / (n - 1)); };
    var y = function (v) { return B - (B - T) * (v / yMax); };
    var step = n > 1 ? (R - L) / (n - 1) : R - L;
    var out = [];

    // Thresholds named in words, so "is 7 any good?" needs no legend lookup.
    [[12, "Fast"], [6, "Mod"], [3, "Slow"]].forEach(function (pair) {
      if (pair[0] > yMax) { return; }
      out.push('<line x1="' + L + '" y1="' + y(pair[0]) + '" x2="' + R +
        '" y2="' + y(pair[0]) + '" stroke="var(--divider-color)" ' +
        'stroke-width="0.6" stroke-dasharray="2 3"/>');
      out.push('<text x="' + (L - 5) + '" y="' + (y(pair[0]) + 3) +
        '" font-size="8.5" text-anchor="end" ' +
        'fill="var(--secondary-text-color)">' + pair[1] + "</text>");
    });

    out.push('<defs><pattern id="' + uid + '-wet" width="4" height="4" ' +
      'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
      '<line x1="0" y1="0" x2="0" y2="4" stroke="var(--secondary-text-color)" ' +
      'stroke-width="1"/></pattern></defs>');

    // Rain sits below the axis so it never collides with a low series, and
    // contiguous wet hours merge into one block rather than reading as stripes.
    var runStart = null;
    for (var i = 0; i <= n; i++) {
      var wet = i < n && series[i].wet;
      if (wet && runStart === null) { runStart = i; }
      if (!wet && runStart !== null) {
        var rx0 = x(runStart) - step / 2;
        var rx1 = x(i - 1) + step / 2;
        out.push('<rect x="' + rx0 + '" y="' + (B + 4) + '" width="' +
          (rx1 - rx0) + '" height="7" fill="url(#' + uid + '-wet)" ' +
          'stroke="var(--divider-color)" stroke-width="0.5">' +
          "<title>Rain likely</title></rect>");
        runStart = null;
      }
    }

    out.push('<line x1="' + L + '" y1="' + B + '" x2="' + R + '" y2="' + B +
      '" stroke="var(--divider-color)" stroke-width="1"/>');

    if (typeof indoor === "number") {
      out.push('<line x1="' + L + '" y1="' + y(indoor) + '" x2="' + R +
        '" y2="' + y(indoor) + '" stroke="var(--primary-text-color)" ' +
        'stroke-width="1.4" stroke-dasharray="1 2" opacity="0.55"/>');
    }

    // Twelve-hour labels ("8 PM") need more room than "20", so fewer of them
    // fit across the same axis.
    var fmt = this._fmt();
    var maxTicks = fmt.hour12 === false ? 8 : 6;
    var every = Math.max(1, Math.ceil(n / maxTicks));
    var points = function (key) {
      return series.map(function (h, i) { return x(i) + "," + y(h[key]); }).join(" ");
    };

    out.push('<polyline points="' + points("cov") + '" fill="none" ' +
      'stroke="var(--primary-text-color)" stroke-width="1.7" stroke-linejoin="round"/>');
    series.forEach(function (h, i) {
      if (i % every) { return; }
      out.push('<circle cx="' + x(i) + '" cy="' + y(h.cov) + '" r="2" ' +
        'fill="var(--primary-text-color)"/>');
    });

    out.push('<polyline points="' + points("sun") + '" fill="none" ' +
      'stroke="var(--primary-text-color)" stroke-width="1.7" ' +
      'stroke-dasharray="5 3" stroke-linejoin="round"/>');
    series.forEach(function (h, i) {
      if (i % every) { return; }
      var cx = x(i), cy = y(h.sun);
      out.push('<path d="M' + cx + " " + (cy - 2.7) + " L" + (cx + 2.7) + " " +
        cy + " L" + cx + " " + (cy + 2.7) + " L" + (cx - 2.7) + " " + cy +
        ' Z" fill="var(--card-background-color)" ' +
        'stroke="var(--primary-text-color)" stroke-width="1.1"/>');
    });

    // Direct labels, nudged apart when they would otherwise sit on top of
    // each other — a third channel telling the series apart.
    var labels = [
      [y(series[n - 1].sun), "Sun"],
      [y(series[n - 1].cov), "Cover"],
    ];
    if (typeof indoor === "number") {
      labels.push([y(indoor), indoorName]);
    }
    labels.sort(function (a, b) { return a[0] - b[0]; });
    for (var k = 1; k < labels.length; k++) {
      if (labels[k][0] - labels[k - 1][0] < 11) {
        labels[k][0] = labels[k - 1][0] + 11;
      }
    }
    labels.forEach(function (label) {
      out.push('<text x="' + (R + 5) + '" y="' + Math.min(label[0] + 3, H - 30) +
        '" font-size="9" fill="var(--primary-text-color)">' +
        _lwEscape(label[1]) + "</text>");
    });

    out.push('<line x1="' + L + '" y1="' + T + '" x2="' + L + '" y2="' + B +
      '" stroke="var(--secondary-text-color)" stroke-width="0.8" ' +
      'stroke-dasharray="1 2"/>');
    out.push('<text x="' + (L + 3) + '" y="' + (T + 6) + '" font-size="8" ' +
      'fill="var(--secondary-text-color)">now</text>');

    series.forEach(function (h, i) {
      if (i % every) { return; }
      // Formatted from the timestamp rather than using the server's pre-baked
      // hhmm, so the axis and the timing rows can never disagree.
      out.push('<text x="' + x(i) + '" y="' + (H - 6) + '" font-size="8.5" ' +
        'text-anchor="middle" fill="var(--secondary-text-color)">' +
        _lwEscape(_lwHour(h.ts, fmt) || h.hhmm) + "</text>");
    });

    return '<svg viewBox="0 0 ' + W + " " + H + '" role="img" ' +
      'preserveAspectRatio="xMidYMid meet" aria-label="' +
      _lwEscape(this._chartDescription(series, indoor, indoorName)) + '">' +
      out.join("") + "</svg>";
  }

  /** What the chart says, in words, for anyone who cannot see it. */
  _chartDescription(series, indoor, indoorName) {
    var peakSun = series[0], peakCov = series[0];
    series.forEach(function (h) {
      if (h.sun > peakSun.sun) { peakSun = h; }
      if (h.cov > peakCov.cov) { peakCov = h; }
    });
    var parts = [
      "Drying forecast for the next " + series.length + " hours.",
      "In the sun peaks at " + peakSun.sun + " around " + peakSun.hhmm + ".",
      "Under cover peaks at " + peakCov.cov + " around " + peakCov.hhmm + ".",
    ];
    if (typeof indoor === "number") {
      parts.push(indoorName + " is at " + indoor + " for comparison.");
    }
    var wet = series.filter(function (h) { return h.wet; });
    if (wet.length) {
      parts.push("Rain likely from " + wet[0].hhmm + " to " +
        wet[wet.length - 1].hhmm + ".");
    }
    return parts.join(" ");
  }

  _switch(attrs) {
    if (!this._config.show_switch) { return ""; }
    var on = !!attrs.washing_out;
    return '<button class="wash" type="button" aria-pressed="' + on + '">' +
      "Washing is on the line</button>";
  }

  // --- render ------------------------------------------------------------

  _render() {
    var state = this._state();
    if (!state) {
      this.shadowRoot.innerHTML = this._styles() +
        '<ha-card><div class="pad"><p class="empty">' +
        _lwEscape(this._config.entity || "No entity") +
        " is not available yet.</p></div></ha-card>";
      return;
    }

    var attrs = state.attributes || {};
    var good = !!attrs.good_drying_day;
    var klingon = this._klingon(attrs);
    var compact = !!this._config.compact;
    var advice = _lwAdvice(attrs, this._fmt());

    var body = this._banner(attrs, good, klingon) + '<div class="pad">' +
      this._summary(state, attrs) +
      (advice ? '<p class="advice">' + _lwEscape(advice) + "</p>" : "") +
      (compact ? "" : this._spots(attrs)) +
      this._timing(attrs) +
      (compact ? "" : this._forecast(attrs)) +
      this._switch(attrs) +
      '<div class="foot"><span>' +
      _lwEscape(_lwTime(state.last_updated, this._fmt())) +
      '</span><span>v' + CARD_VERSION + "</span></div></div>";

    this.shadowRoot.innerHTML = this._styles() +
      "<ha-card" + (this._config.title
        ? ' header="' + _lwEscape(this._config.title) + '"' : "") +
      ">" + body + "</ha-card>";

    var button = this.shadowRoot.querySelector("button.wash");
    if (button) {
      var self = this;
      button.addEventListener("click", function () { self._toggleWashing(attrs); });
    }
  }

  _toggleWashing(attrs) {
    if (!this._hass) { return; }
    this._hass.callService("laundry_weather", "set_washing_out", {
      washing_out: !attrs.washing_out,
    });
  }

  _styles() {
    return "<style>" +
      "ha-card{overflow:hidden}" +
      ".pad{padding:16px}" +
      ".banner{background:var(--secondary-background-color,transparent)}" +
      ".banner img{display:block;width:100%;height:auto}" +
      ".banner .caption{padding:6px 16px 0;font-style:italic;font-weight:600;" +
      "font-size:15px;text-align:center}" +
      ".sub{font-size:13px;color:var(--secondary-text-color)}" +
      ".advice{margin:10px 0 0;font-size:14px;line-height:1.45}" +
      "table.spots{width:100%;border-collapse:collapse;margin-top:14px;font-size:14px}" +
      "table.spots th{text-align:left;font-size:11px;font-weight:500;" +
      "letter-spacing:.06em;text-transform:uppercase;" +
      "color:var(--secondary-text-color);padding:0 0 6px;" +
      "border-bottom:1px solid var(--divider-color)}" +
      "table.spots th.num,table.spots td.num{text-align:right}" +
      "table.spots td{padding:7px 0;border-bottom:1px solid var(--divider-color)}" +
      "table.spots tr:last-child td{border-bottom:0}" +
      "tr.best td{font-weight:600}" +
      ".marks{font-family:monospace;letter-spacing:1px;margin-right:8px;font-size:13px}" +
      "td.num{font-variant-numeric:tabular-nums;color:var(--secondary-text-color)}" +
      "dl.timing{margin:14px 0 0;font-size:14px}" +
      ".trow{display:flex;justify-content:space-between;gap:12px;padding:6px 0;" +
      "border-bottom:1px solid var(--divider-color)}" +
      ".trow:last-child{border-bottom:0}" +
      "dl.timing dt{color:var(--secondary-text-color);flex:0 0 auto}" +
      "dl.timing dd{margin:0;text-align:right;flex:1 1 auto}" +
      ".cd{color:var(--secondary-text-color);font-style:normal}" +
      ".strip{margin-top:16px}" +
      ".strip h4{margin:0 0 6px;font-size:11px;font-weight:500;" +
      "letter-spacing:.06em;text-transform:uppercase;color:var(--secondary-text-color)}" +
      ".legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;" +
      "color:var(--secondary-text-color);margin-bottom:4px}" +
      ".legend span{display:inline-flex;align-items:center;gap:5px}" +
      ".legend svg{display:block}" +
      ".strip>svg{width:100%;height:auto;display:block;overflow:visible}" +
      ".note,.empty{font-size:12px;color:var(--secondary-text-color);margin:6px 0 0}" +
      ".empty{font-size:13px}" +
      "button.wash{margin-top:14px;width:100%;padding:10px;font:inherit;" +
      "font-size:14px;background:transparent;color:var(--primary-text-color);" +
      "border:1px solid var(--divider-color);border-radius:8px;cursor:pointer}" +
      'button.wash[aria-pressed="true"]{border-color:var(--primary-text-color);' +
      "font-weight:600}" +
      ".foot{margin-top:12px;font-size:11px;color:var(--secondary-text-color);" +
      "display:flex;justify-content:space-between}" +
      "</style>";
  }
}

class LaundryWeatherCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = Object.assign({}, DEFAULTS);
    this._hass = null;
    this._lastRenderKey = null;
  }

  setConfig(config) {
    this._config = Object.assign({}, DEFAULTS, config);
    this._renderIfChanged();
  }

  // Home Assistant assigns `hass` on every state change — several times a
  // second on a busy instance. Re-rendering on each one destroyed and rebuilt
  // the very <select> the user had just opened, so the clock-format dropdown
  // flashed open and shut. Nothing here depends on live state except the list
  // of candidate sensors, so compare that and otherwise leave the DOM alone.
  // Same guard the card itself uses for `_lastDataJSON`.
  set hass(hass) {
    this._hass = hass;
    this._renderIfChanged();
  }

  _renderKey() {
    return JSON.stringify([this._config, this._candidates()]);
  }

  _renderIfChanged() {
    var key = this._renderKey();
    if (key === this._lastRenderKey) { return; }
    this._lastRenderKey = key;
    this._render();
  }

  _emit(changes) {
    this._config = Object.assign({}, this._config, changes);
    // Deliberately no re-render. The control the user just touched already
    // shows its new value, and Home Assistant echoes the change straight back
    // through `setConfig` — so rendering here rebuilt the editor twice per
    // keystroke. Recording the key now makes that echo a no-op.
    this._lastRenderKey = this._renderKey();
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    }));
  }

  _candidates() {
    if (!this._hass) { return []; }
    var states = this._hass.states;
    return Object.keys(states).filter(function (id) {
      return id.indexOf("sensor.") === 0 && states[id].attributes &&
        states[id].attributes.spots !== undefined;
    });
  }

  _render() {
    var config = this._config;
    var options = this._candidates().map(function (id) {
      return '<option value="' + _lwEscape(id) + '"' +
        (id === config.entity ? " selected" : "") + ">" + _lwEscape(id) +
        "</option>";
    }).join("");

    var toggles = [
      ["show_mascot", "Show the mascot"],
      ["show_spots", "Show the list of places"],
      ["show_timing", "Show the timings"],
      ["show_forecast", "Show the drying forecast"],
      ["show_switch", "Show the washing-on-the-line button"],
      ["compact", "Compact — headline and timings only"],
    ].map(function (pair) {
      return '<label class="row"><input type="checkbox" data-key="' + pair[0] +
        '"' + (config[pair[0]] ? " checked" : "") + "> " + pair[1] + "</label>";
    }).join("");

    this.shadowRoot.innerHTML =
      "<style>" +
      ".wrap{display:flex;flex-direction:column;gap:10px;padding:8px 0}" +
      "label{font-size:14px}" +
      ".row{display:flex;align-items:center;gap:8px}" +
      "select,input[type=text],input[type=number]{width:100%;padding:6px;" +
      "font:inherit;box-sizing:border-box}" +
      ".hint{font-size:12px;color:var(--secondary-text-color);margin:-4px 0 4px}" +
      "</style>" +
      '<div class="wrap">' +
      "<label>Recommendation sensor<select data-key=\"entity\">" +
      '<option value="">Choose…</option>' + options + "</select></label>" +
      '<p class="hint">Everything on the card comes from this one sensor.</p>' +
      "<label>Card title (optional)<input type=\"text\" data-key=\"title\" " +
      'value="' + _lwEscape(config.title) + '"></label>' +
      toggles +
      "<label>Clock format" +
      "<select data-key=\"time_format\">" +
      ["auto", "12", "24"].map(function (v) {
        var label = v === "auto" ? "Follow Home Assistant"
          : (v === "12" ? "12-hour (2:30 PM)" : "24-hour (14:30)");
        return '<option value="' + v + '"' +
          (config.time_format === v ? " selected" : "") + ">" + label + "</option>";
      }).join("") + "</select></label>" +
      "<label>Hours on the forecast chart<input type=\"number\" min=\"6\" " +
      'max="48" data-key="forecast_hours" value="' +
      _lwEscape(config.forecast_hours) + '"></label>' +
      '<label class="row"><input type="checkbox" data-key="klingon"' +
      (config.klingon === true ? " checked" : "") + "> Klingon headline</label>" +
      '<p class="hint">Leave unticked to follow the integration setting.</p>' +
      "<label>Your own good-day picture (optional)<input type=\"text\" " +
      'data-key="image_good" value="' + _lwEscape(config.image_good) +
      '" placeholder="/local/my-good-day.png"></label>' +
      "<label>Your own bad-day picture (optional)<input type=\"text\" " +
      'data-key="image_bad" value="' + _lwEscape(config.image_bad) +
      '" placeholder="/local/my-bad-day.png"></label>' +
      "</div>";

    var self = this;
    this.shadowRoot.querySelectorAll("[data-key]").forEach(function (node) {
      node.addEventListener("change", function (event) {
        var key = event.target.getAttribute("data-key");
        var value;
        if (event.target.type === "checkbox") {
          value = event.target.checked;
          if (key === "klingon" && !value) { value = null; }
        } else if (event.target.type === "number") {
          value = Number(event.target.value);
        } else {
          value = event.target.value;
        }
        var changes = {};
        changes[key] = value;
        self._emit(changes);
      });
    });
  }
}

if (!customElements.get("laundry-weather-card")) {
  customElements.define("laundry-weather-card", LaundryWeatherCard);
}
if (!customElements.get("laundry-weather-card-editor")) {
  customElements.define("laundry-weather-card-editor", LaundryWeatherCardEditor);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "laundry-weather-card",
  name: "Laundry Weather Card",
  description: "Where to hang the washing, and when to bring it in.",
  preview: true,
  documentationURL: "https://github.com/loryanstrant/HA-Laundry-Weather",
});

console.info(
  "%c LAUNDRY-WEATHER-CARD %c v" + CARD_VERSION + " ",
  "color:#fff;background:#3d5afe;font-weight:700",
  "color:#3d5afe;background:#fff;font-weight:700"
);
