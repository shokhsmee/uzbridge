/*
 * uzbridge amoCRM widget.
 *
 *  - Lead card (lcard-1): payment links and SMS, as tabs when both are on.
 *  - Настройки → uzbridge (advanced_settings): which payment providers, SMS and
 *    SMS templates amoCRM uses, and whether links become amoCRM invoices.
 *  - Воронка (digital_pipeline): "create payment link" / "send SMS" actions,
 *    now or after a delay; amoCRM posts the trigger to our webhook_url.
 *  - SMS as a feed source (add_source 'sms') on phone numbers.
 *
 * Every call goes through self.$authorizedAjax, which adds an X-Auth-Token
 * JWT signed with the integration's client secret; the backend maps its
 * account_id to the company. __API_BASE__ is replaced by build.py.
 */
define(['jquery'], function ($) {
  var API = '__API_BASE__';

  // Colours follow amoCRM's light or dark theme (see theme()).
  var CSS = [
    '.uzb{--bg:#fff;--soft:#f4f6f6;--line:#dde3e2;--ink:#14201f;--muted:#5f6b69;--accent:#12877f;--accent-ink:#0d6b64;',
    '--ok:#1d7a3a;--ok-bg:#e3f2e7;--warn:#8a5f00;--warn-bg:#f7eed8;--bad:#a33b2b;--bad-bg:#f7e3df;',
    'font-size:13px;line-height:1.45;color:var(--ink)}',
    '.uzb.uzb-dark{--bg:#1c2b33;--soft:#243640;--line:#34495a;--ink:#e8eef0;--muted:#9fb0b8;--accent:#2bb3a6;--accent-ink:#5fd0c5;',
    '--ok:#7fd49a;--ok-bg:#1f3a2b;--warn:#f0c46a;--warn-bg:#3d3320;--bad:#f39a8a;--bad-bg:#43282a}',
    '.uzb *{box-sizing:border-box}',
    '.uzb label{display:block;font-size:12px;color:var(--muted);margin:10px 0 4px}',
    '.uzb input[type=text],.uzb input:not([type]),.uzb select{width:100%;height:34px;border:1px solid var(--line);border-radius:8px;',
    'padding:0 10px;font-size:13px;background:var(--bg);color:var(--ink)}',
    '.uzb input:focus,.uzb select:focus{border-color:var(--accent);outline:none}',
    '.uzb .uzb-btn{margin-top:12px;width:100%;height:36px;border:0;border-radius:8px;background:var(--accent);color:#fff;',
    'font-weight:600;font-size:13px;cursor:pointer}',
    '.uzb .uzb-btn:hover{filter:brightness(1.07)}.uzb .uzb-btn[disabled]{opacity:.5;cursor:default}',
    '.uzb .uzb-msg{margin-top:10px;padding:8px 10px;border-radius:8px;background:var(--warn-bg);color:var(--warn)}',
    '.uzb .uzb-err{background:var(--bad-bg);color:var(--bad)}.uzb .uzb-okmsg{background:var(--ok-bg);color:var(--ok)}',
    '.uzb h4{margin:18px 0 8px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:600}',
    '.uzb .uzb-tabs{display:flex;gap:4px;padding:3px;background:var(--soft);border-radius:9px;margin-bottom:6px}',
    '.uzb .uzb-tab{flex:1;height:30px;border:0;border-radius:7px;background:transparent;color:var(--muted);font-weight:600;cursor:pointer;font-size:13px}',
    '.uzb .uzb-tab.on{background:var(--bg);color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,.12)}',
    '.uzb .uzb-inv{border:1px solid var(--line);border-radius:8px;padding:9px 10px;margin-bottom:6px;background:var(--bg)}',
    '.uzb .uzb-row{display:flex;justify-content:space-between;align-items:center;gap:8px}',
    '.uzb .uzb-amt{font-weight:600;font-variant-numeric:tabular-nums}',
    '.uzb .uzb-pill{font-size:11px;padding:2px 8px;border-radius:99px;white-space:nowrap;font-weight:500}',
    '.uzb .p-pending{background:var(--warn-bg);color:var(--warn)}.uzb .p-paid,.uzb .p-on{background:var(--ok-bg);color:var(--ok)}',
    '.uzb .p-cancelled,.uzb .p-off{background:var(--soft);color:var(--muted)}.uzb .p-refunded,.uzb .p-bad{background:var(--bad-bg);color:var(--bad)}',
    '.uzb .uzb-link{display:flex;gap:4px;margin-top:8px}',
    '.uzb .uzb-link input{height:28px!important;font-size:11px!important;background:var(--soft)!important}',
    '.uzb .uzb-mini{height:28px;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:7px;padding:0 9px;cursor:pointer;font-size:12px;white-space:nowrap}',
    '.uzb .uzb-meta{font-size:11px;color:var(--muted);margin-top:2px}',
    '.uzb .uzb-empty{color:var(--muted);padding:6px 0}',
    // settings page
    '.uzb-page{max-width:760px;padding:28px 32px 60px}',
    '.uzb-page .uzb-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:20px}',
    '.uzb-page .uzb-head h2{margin:0;font-size:20px;font-weight:600;color:var(--ink)}',
    '.uzb-page .uzb-head a{color:var(--accent-ink);text-decoration:none;font-weight:500}',
    '.uzb-page .uzb-card{background:var(--bg);border:1px solid var(--line);border-radius:12px;margin-bottom:16px;overflow:hidden}',
    '.uzb-page .uzb-card-h{padding:14px 18px;border-bottom:1px solid var(--line)}',
    '.uzb-page .uzb-card-h b{font-size:14px}.uzb-page .uzb-card-h p{margin:3px 0 0;color:var(--muted);font-size:12px}',
    '.uzb-page .uzb-item{display:flex;align-items:center;gap:12px;padding:12px 18px;border-top:1px solid var(--line)}',
    '.uzb-page .uzb-card-h + .uzb-item{border-top:0}',
    '.uzb-page .uzb-item .uzb-grow{flex:1;min-width:0}',
    '.uzb-page .uzb-item .uzb-grow div{overflow:hidden;text-overflow:ellipsis}',
    '.uzb-page .uzb-note{padding:12px 18px;color:var(--muted)}',
    '.uzb-page ol{margin:0;padding:12px 18px 14px 36px;color:var(--ink)}.uzb-page ol li{margin:4px 0}',
    '.uzb-page .uzb-save{display:flex;align-items:center;gap:12px}',
    '.uzb-page .uzb-save .uzb-btn{width:auto;padding:0 22px;margin:0}',
    '.uzb-page .uzb-save .uzb-msg{margin:0}',
    '.uzb-page .uzb-var{display:grid;grid-template-columns:170px 1fr 34px;gap:8px;align-items:center;padding:8px 18px}',
    '.uzb-page .uzb-var:first-of-type{padding-top:14px}',
    '.uzb-page .uzb-key{display:flex;align-items:center;border:1px solid var(--line);border-radius:8px;background:var(--bg);height:34px}',
    '.uzb-page .uzb-key span{color:var(--muted);font-family:monospace;padding:0 4px 0 8px}.uzb-page .uzb-key span:last-child{padding:0 8px 0 4px}',
    '.uzb-page .uzb-key input{border:0!important;height:32px!important;padding:0!important;font-family:monospace}',
    '.uzb-page .uzb-chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}',
    '.uzb-page .uzb-chips code{background:var(--soft);border-radius:6px;padding:1px 6px;font-size:12px;color:var(--ink)}',
    '.uzb-page .uzb-add{margin:8px 18px 14px;height:32px;border:1px dashed var(--line);border-radius:8px;background:transparent;color:var(--accent-ink);cursor:pointer;padding:0 14px;font-weight:600}',
    // switch
    '.uzb .uzb-sw{position:relative;display:inline-block;width:38px;height:22px;flex:none}',
    '.uzb .uzb-sw input{opacity:0;width:0;height:0;position:absolute}',
    '.uzb .uzb-sw span{position:absolute;inset:0;border-radius:99px;background:var(--line);transition:.15s;cursor:pointer}',
    '.uzb .uzb-sw span:before{content:"";position:absolute;width:16px;height:16px;left:3px;top:3px;border-radius:50%;background:#fff;transition:.15s;box-shadow:0 1px 2px rgba(0,0,0,.25)}',
    '.uzb .uzb-sw input:checked + span{background:var(--accent)}.uzb .uzb-sw input:checked + span:before{transform:translateX(16px)}',
    '.uzb .uzb-sw input:disabled + span{opacity:.45;cursor:default}',
    // digital pipeline form
    '.uzb-dp{padding:4px 0 8px}.uzb-dp > label:first-child{margin-top:0}',
    // shaxmatka: unit statuses, the showroom overlay, the stage table
    '.uzb .p-free{background:#e2f3e8;color:#1b7a47}.uzb .p-interest{background:#e3ecfa;color:#2459ab}',
    '.uzb .p-reserved{background:#fbf0d6;color:#8a5f00}.uzb .p-sold{background:var(--soft);color:var(--muted)}.uzb .p-closed{background:var(--soft);color:var(--muted)}',
    '.uzb-sr{position:fixed;inset:0;z-index:100000;background:rgba(10,20,20,.55);display:flex;flex-direction:column;padding:18px}',
    '.uzb-sr-bar{display:flex;justify-content:flex-end;margin-bottom:8px}',
    '.uzb-sr-bar button{height:34px;padding:0 16px;border:0;border-radius:8px;background:#fff;color:#14201f;font-weight:600;cursor:pointer;font-size:13px}',
    '.uzb-sr iframe{flex:1;width:100%;border:0;border-radius:12px;background:#f3f5f5}',
    '.uzb-page .uzb-stage{display:grid;grid-template-columns:1fr 200px;gap:10px;align-items:center;padding:7px 18px;border-top:1px solid var(--line)}',
    '.uzb-page .uzb-stage i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:8px;vertical-align:middle}',
    '.uzb-page .uzb-pipe{padding:10px 18px 6px;border-top:1px solid var(--line);font-weight:600;background:var(--soft)}',
    '.uzb-page .uzb-stage select{height:32px}',
    '.uzb-page .uzb-card-h a,.uzb-page .uzb-note a{color:var(--accent-ink);text-decoration:none;font-weight:500}',
    // settings page: one tab per service the account has
    '.uzb-page .uzb-ptabs{display:flex;gap:2px;border-bottom:1px solid var(--line);margin:0 0 18px;overflow-x:auto}',
    '.uzb-page .uzb-ptab{padding:10px 16px;border:0;background:none;color:var(--muted);font-weight:600;font-size:13px;cursor:pointer;',
    'border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap}',
    '.uzb-page .uzb-ptab:hover{color:var(--ink)}.uzb-page .uzb-ptab.on{color:var(--ink);border-bottom-color:var(--accent)}',
    '.uzb-page .uzb-ptab i{font-style:normal;display:inline-block;width:7px;height:7px;border-radius:50%;margin-left:7px;vertical-align:1px;background:var(--line)}',
    '.uzb-page .uzb-ptab i.on{background:var(--accent)}',
    '.uzb-page [data-pane][hidden]{display:none}',
    '.uzb-page .uzb-more{color:var(--muted);font-size:12px;margin:-6px 0 16px}.uzb-page .uzb-more a{color:var(--accent-ink)}'
  ].join('');

  var DELAYS = [0, 5, 15, 30, 60, 180, 360, 720, 1440, 2880, 4320, 10080];

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function short(text, n) {
    return text.length > n ? text.slice(0, n - 1) + '…' : text;
  }

  // amoCRM's dark theme: judge by the page background's brightness.
  function theme() {
    var el = document.querySelector('#page_holder') || document.body;
    var m = (getComputedStyle(el).backgroundColor || '').match(/\d+/g);
    if (!m || (m.length > 3 && Number(m[3]) === 0)) m = (getComputedStyle(document.body).backgroundColor || '').match(/\d+/g);
    if (!m) return '';
    var lum = 0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2];
    return lum < 110 ? ' uzb-dark' : '';
  }

  var Widget = function () {
    var self = this;
    var state = { leadId: 0, busy: false, tab: 'pay', ctx: null, realty: null };

    function t(key) {
      return self.i18n('ui')[key] || key;
    }

    function leadId() {
      if (self.system().area !== 'lcard') return 0;
      return (window.APP && APP.data && APP.data.current_card && APP.data.current_card.id) || 0;
    }

    function leadPrice() {
      var v = $('input[name="lead[PRICE]"]').val();
      return v ? String(v).replace(/[^\d.,]/g, '') : '';
    }

    function leadName() {
      try {
        return APP.data.current_card.model.get('name') || '';
      } catch (e) {
        return $('#person_n').val() || '';
      }
    }

    function userName() {
      try {
        return APP.constant('user').name || '';
      } catch (e) {
        return '';
      }
    }

    function call(method, path, body) {
      return self.$authorizedAjax({
        url: API + '/api/widget' + path,
        type: method,
        dataType: 'json',
        contentType: 'application/json',
        data: body ? JSON.stringify(body) : undefined
      });
    }

    function errorText(xhr) {
      if (xhr && xhr.status === 401) return t('not_connected');
      try {
        var d = xhr.responseJSON && xhr.responseJSON.detail;
        if (typeof d === 'string') return d;
      } catch (e) {}
      return t('error');
    }

    // Versioned: amoCRM keeps the page (and an older widget's styles) across a widget upgrade.
    var CSS_ID = 'uzb-css-151';
    function css() {
      if (document.getElementById(CSS_ID)) return;
      $('style[id^="uzb-css"]').remove();
      $('head').append('<style id="' + CSS_ID + '">' + CSS + '</style>');
    }

    function toggle(id, checked, disabled, attrs) {
      return '<label class="uzb-sw"><input type="checkbox" id="' + esc(id) + '"' + (attrs || '') +
        (checked ? ' checked' : '') + (disabled ? ' disabled' : '') + '><span></span></label>';
    }

    // ---------------------------------------------------------------- lead card

    function $root() {
      return $('#uzb-root');
    }

    function renderInvoices(invoices) {
      if (!invoices.length) return '<p class="uzb-empty">' + esc(t('empty')) + '</p>';
      return invoices
        .map(function (inv) {
          var link =
            inv.status === 'pending'
              ? '<div class="uzb-link"><input readonly value="' + esc(inv.url) + '">' +
                '<button class="uzb-mini" data-copy="' + esc(inv.url) + '">' + esc(t('copy')) + '</button>' +
                '<button class="uzb-mini" title="' + esc(t('cancel')) + '" data-cancel="' + esc(inv.id) + '">✕</button></div>'
              : '';
          var via = inv.paid_via ? ' · ' + esc(t('via')) + ' ' + esc(inv.paid_via) : '';
          return (
            '<div class="uzb-inv"><div class="uzb-row"><span class="uzb-amt">' + esc(inv.amount) + ' UZS</span>' +
            '<span class="uzb-pill p-' + esc(inv.status) + '">' + esc(t('st_' + inv.status)) + '</span></div>' +
            '<div class="uzb-meta">' + esc(inv.number) + via + '</div>' + link + '</div>'
          );
        })
        .join('');
    }

    function payPane(ctx) {
      return (
        '<label for="uzb-amount">' + esc(t('amount')) + '</label>' +
        '<input id="uzb-amount" inputmode="decimal" value="' + esc(leadPrice()) + '">' +
        '<label for="uzb-desc">' + esc(t('description')) + '</label>' +
        '<input id="uzb-desc" maxlength="255">' +
        '<button class="uzb-btn" id="uzb-create"' + (state.busy ? ' disabled' : '') + '>' + esc(t('create')) + '</button>' +
        '<h4>' + esc(t('history')) + '</h4>' + renderInvoices(ctx.invoices)
      );
    }

    function smsPane(ctx) {
      if (!ctx.sms_templates.length) return '<p class="uzb-empty">' + esc(t('sms_none')) + '</p>';
      var opts = ctx.sms_templates.map(function (tpl) {
        return '<option value="' + tpl.id + '">' + esc(short(tpl.text, 70)) + '</option>';
      }).join('');
      return (
        '<label for="uzb-sms-tpl">' + esc(t('sms_pick')) + '</label>' +
        '<select id="uzb-sms-tpl">' + opts + '</select>' +
        '<div class="uzb-meta" id="uzb-sms-preview" style="margin-top:8px;white-space:pre-wrap">' + esc(ctx.sms_templates[0].text) + '</div>' +
        '<button class="uzb-btn" id="uzb-sms-send">' + esc(t('sms_send')) + '</button>'
      );
    }

    function docsPane(docs) {
      var tpls = docs.templates;
      var cur = tpls.filter(function (x) { return x.id === state.docTpl; })[0] || tpls[0];
      state.docTpl = cur.id;
      var fmt = state.docFmt || cur.format;
      var opts = tpls.map(function (x) {
        return '<option value="' + x.id + '"' + (x.id === cur.id ? ' selected' : '') + '>' + esc(x.name) + '</option>';
      }).join('');
      var made = docs.documents.length
        ? docs.documents.map(function (d) {
            return '<div class="uzb-inv"><div class="uzb-row"><span class="uzb-amt">№ ' + esc(d.number) + '</span>' +
              '<span class="uzb-pill p-on">' + esc(d.format === 'pdf' ? 'PDF' : 'Word') + '</span></div>' +
              '<div class="uzb-meta">' + esc(d.template) + '</div>' +
              '<div class="uzb-link"><a class="uzb-mini" href="' + esc(d.url) + '" target="_blank" rel="noopener" style="text-decoration:none;line-height:26px">' + esc(t('d_open')) + '</a>' +
              '<button class="uzb-mini" data-doc-regen="' + d.template_id + '" data-doc-fmt="' + esc(d.format) + '">' + esc(t('d_regen')) + '</button></div></div>';
          }).join('')
        : '<p class="uzb-empty">' + esc(t('d_none')) + '</p>';
      return (
        '<label for="uzb-doc-tpl">' + esc(t('d_template')) + '</label><select id="uzb-doc-tpl">' + opts + '</select>' +
        '<div class="uzb-meta" style="margin-top:6px">' + esc(t('d_next')) + ' <b>' + esc(cur.next) + '</b></div>' +
        '<label>' + esc(t('d_format')) + '</label><div class="uzb-tabs" style="margin:0">' +
        '<button class="uzb-tab' + (fmt === 'docx' ? ' on' : '') + '" data-doc-format="docx">Word</button>' +
        '<button class="uzb-tab' + (fmt === 'pdf' ? ' on' : '') + '" data-doc-format="pdf">PDF</button></div>' +
        '<button class="uzb-btn" id="uzb-doc-gen"' + (state.busy ? ' disabled' : '') + '>' + esc(state.busy ? t('d_making') : t('d_generate')) + '</button>' +
        '<h4>' + esc(t('d_made')) + '</h4>' + made
      );
    }

    var UNIT_ST = ['free', 'interest', 'reserved', 'sold', 'closed'];

    function realtyPane(r) {
      var list = r.units.length
        ? r.units.map(function (u) {
            var off = u.status === 'sold' ? '' :
              '<button class="uzb-mini" title="' + esc(t('r_detach')) + '" data-unit-detach="' + u.id + '">✕</button>';
            return '<div class="uzb-inv"><div class="uzb-row"><span class="uzb-amt">' + esc(u.label) + '</span>' +
              '<span class="uzb-pill p-' + esc(u.status) + '">' + esc(u.status_name) + '</span></div>' +
              '<div class="uzb-row"><div class="uzb-meta">' + esc(u.project) + ' · ' +
              esc(u.rooms ? u.rooms + t('r_rooms') : t('r_studio')) + ' · ' + esc(u.area) + ' m² · ' + esc(t('r_floor')) + ' ' + esc(u.floor) +
              '<br><b style="color:var(--ink)">' + esc(u.price) + '</b></div>' + off + '</div></div>';
          }).join('')
        : '<p class="uzb-empty">' + esc(t('r_none')) + '</p>';
      return '<button class="uzb-btn" id="uzb-showroom" style="margin-top:4px"' + (state.busy ? ' disabled' : '') + '>' +
        esc(t('r_open')) + '</button>' + '<h4>' + esc(t('r_units')) + '</h4>' + list +
        (state.realtyChanged ? '<div class="uzb-msg uzb-okmsg">' + esc(t('r_reload_hint')) +
          ' <a href="#" id="uzb-card-reload">' + esc(t('r_reload')) + '</a></div>' : '');
    }

    // The showroom (our page) full screen over the card; it tells us when a unit was attached.
    function openShowroom() {
      state.busy = true;
      paint(state.ctx);
      call('POST', '/realty/session', { lead_id: state.leadId, user_name: userName() })
        .done(function (res) {
          state.busy = false;
          paint(state.ctx);
          var $sr = $('<div class="uzb-sr"><div class="uzb-sr-bar"><button type="button">' + esc(t('r_close')) + ' ✕</button></div>' +
            '<iframe allow="clipboard-write"></iframe></div>');
          $sr.find('iframe').attr('src', res.url);
          var origin = res.url.split('/').slice(0, 3).join('/');
          var onMsg = function (e) {
            var d = e.originalEvent.data;
            if (e.originalEvent.origin !== origin || !d || d.type !== 'uzbridge-realty') return;
            state.realtyChanged = true;
          };
          var close = function () {
            $(window).off('message.uzbsr', onMsg);
            $(document).off('keydown.uzbsr');
            $sr.remove();
            if (state.realtyChanged) load();
          };
          $(window).on('message.uzbsr', onMsg);
          $(document).on('keydown.uzbsr', function (e) { if (e.key === 'Escape') close(); });
          $sr.on('click', '.uzb-sr-bar button', close);
          $('body').append($sr);
        })
        .fail(function (xhr) {
          state.busy = false;
          paint(state.ctx, esc(errorText(xhr)), true);
        });
    }

    function paint(ctx, message, isError) {
      var docs = state.docs;
      var tabs = [];
      if (ctx.providers.length > 0) tabs.push(['pay', t('tab_pay')]);
      if (ctx.sms_ready) tabs.push(['sms', t('tab_sms')]);
      if (docs && docs.enabled && docs.templates.length) tabs.push(['docs', t('tab_docs')]);
      if (state.realty && (state.realty.projects > 0 || state.realty.units.length)) tabs.push(['realty', t('tab_realty')]);
      var keys = tabs.map(function (x) { return x[0]; });
      if (keys.indexOf(state.tab) < 0) state.tab = keys[0];
      var html = '<div class="uzb' + theme() + '">' +
        '<div class="uzb-meta" style="margin:0 0 8px">uzbridge · <b style="color:var(--ink)">' + esc(ctx.company) + '</b></div>';
      if (!tabs.length) {
        html += '<div class="uzb-msg">' + esc(t('nothing_on')) + '</div>';
      } else {
        if (tabs.length > 1) {
          html += '<div class="uzb-tabs">' + tabs.map(function (x) {
            return '<button class="uzb-tab' + (state.tab === x[0] ? ' on' : '') + '" data-tab="' + x[0] + '">' + esc(x[1]) + '</button>';
          }).join('') + '</div>';
        }
        if (message) html += '<div class="uzb-msg' + (isError ? ' uzb-err' : ' uzb-okmsg') + '">' + message + '</div>';
        html += state.tab === 'sms' ? smsPane(ctx) : state.tab === 'docs' ? docsPane(docs) :
          state.tab === 'realty' ? realtyPane(state.realty) : payPane(ctx);
      }
      $root().html(html + '</div>');
    }

    function load(message, isError) {
      state.leadId = leadId();
      if (!state.leadId) {
        $root().html('<div class="uzb' + theme() + '"><p class="uzb-empty">' + esc(t('save_lead_first')) + '</p></div>');
        return;
      }
      $.when(
        call('GET', '/context?lead_id=' + state.leadId),
        call('GET', '/docs?lead_id=' + state.leadId),
        call('GET', '/realty?lead_id=' + state.leadId)
      )
        .done(function (a, b, c) {
          state.ctx = a[0];
          state.docs = b[0];
          state.realty = c[0];
          paint(state.ctx, message === undefined ? '' : esc(message), isError);
        })
        .fail(function (xhr) {
          $root().html('<div class="uzb' + theme() + '"><div class="uzb-msg uzb-err">' + esc(errorText(xhr)) + '</div></div>');
        });
    }

    // ---------------------------------------------------------------- settings page

    function varRow(v, sources) {
      var groups = { lead: t('v_lead'), contact: t('v_contact') };
      var opts = '<option value="">' + esc(t('v_pick')) + '</option>' +
        ['lead', 'contact'].map(function (g) {
          return '<optgroup label="' + esc(groups[g]) + '">' + sources.filter(function (x) { return x.group === g; }).map(function (x) {
            return '<option value="' + esc(x.value) + '"' + (x.value === v.source ? ' selected' : '') + '>' + esc(x.label) + '</option>';
          }).join('') + '</optgroup>';
        }).join('');
      return '<div class="uzb-var"><label class="uzb-key"><span>{</span><input data-var-key value="' + esc(v.key) +
        '" placeholder="muddat"><span>}</span></label><select data-var-source>' + opts + '</select>' +
        '<button class="uzb-mini" data-var-del title="' + esc(t('v_remove')) + '">✕</button></div>';
    }

    function varsSection(vars) {
      return '<section class="uzb-card" id="uzb-vars"><div class="uzb-card-h"><b>' + esc(t('v_title')) + '</b><p>' + esc(t('v_hint')) + '</p>' +
        '<div class="uzb-chips">' + vars.builtins.map(function (b) { return '<code>{' + esc(b) + '}</code>'; }).join('') + '</div></div>' +
        '<div id="uzb-var-rows">' + vars.variables.map(function (v) { return varRow(v, vars.sources); }).join('') + '</div>' +
        '<button class="uzb-add" id="uzb-var-add">+ ' + esc(t('v_add')) + '</button></section>';
    }

    function readVars($holder) {
      return $holder.find('.uzb-var').map(function () {
        return { key: $(this).find('[data-var-key]').val().trim().replace(/[{}]/g, '').toLowerCase(), source: $(this).find('[data-var-source]').val() };
      }).get().filter(function (v) { return v.key || v.source; });
    }

    function docsSection(docs, dashboard) {
      var rows = docs.templates.length
        ? docs.templates.map(function (x) {
            return '<div class="uzb-item"><div class="uzb-grow"><div><b>' + esc(x.name) + '</b></div>' +
              '<div class="uzb-meta">' + esc(x.format === 'pdf' ? 'PDF' : 'Word') + '</div></div>' +
              toggle('uzb-d-' + x.id, x.use, !docs.enabled, ' data-doc-template="' + x.id + '"') + '</div>';
          }).join('')
        : '<div class="uzb-note">' + esc(t('d_no_templates')) + '</div>';
      var docsUrl = (dashboard || '').replace(/\/integrations\/amocrm$/, '/documents');
      return '<section class="uzb-card"><div class="uzb-card-h"><b>' + esc(t('d_title')) + '</b><p>' + esc(t('d_hint')) +
        ' <a href="' + esc(docsUrl) + '" target="_blank" rel="noopener">' + esc(t('d_edit')) + ' ↗</a></p></div>' +
        '<div class="uzb-item"><div class="uzb-grow"><div><b>' + esc(t('d_on')) + '</b></div></div>' +
        toggle('uzb-docs', docs.enabled, false) + '</div>' + rows + '</section>';
    }

    function realtySection(r, dashboard) {
      var url = (dashboard || '').replace(/\/integrations\/amocrm$/, '/shaxmatka');
      var head = '<section class="uzb-card"><div class="uzb-card-h"><b>' + esc(t('r_title')) + '</b><p>' + esc(t('r_hint')) +
        ' <a href="' + esc(url) + '" target="_blank" rel="noopener">' + esc(t('r_edit')) + ' ↗</a></p></div>';
      if (!r.projects.length) return head + '<div class="uzb-note">' + esc(t('r_no_projects')) + '</div></section>';
      var projects = r.projects.map(function (p) {
        return '<div class="uzb-item"><div class="uzb-grow"><div><b>' + esc(p.name) + '</b></div>' +
          '<div class="uzb-meta">' + esc(p.units) + ' ' + esc(t('r_units_n')) + ' · ' + esc(p.currency) + '</div></div>' +
          toggle('uzb-rp-' + p.id, p.use, false, ' data-realty-project="' + p.id + '"') + '</div>';
      }).join('');
      var opts = [['', t('r_st_none')]].concat(UNIT_ST.slice(0, 4).map(function (s) { return [s, t('r_st_' + s)]; }));
      var stages = r.pipelines.map(function (pl) {
        // "Неразобранное" (type 1): a deal can't sit there with a unit, so there's nothing to set
        var list = pl.statuses.filter(function (st) { return st.type !== 1 && !/^неразобран|^incoming|^unsorted/i.test(st.name || ''); });
        return '<div class="uzb-pipe">' + esc(pl.name) + '</div>' + list.map(function (st) {
          return '<div class="uzb-stage"><div><i style="background:' + esc(st.color || '#ccc') + '"></i>' + esc(st.name) + '</div>' +
            '<select data-stage-pipe="' + pl.id + '" data-stage="' + st.id + '">' + opts.map(function (o) {
              return '<option value="' + o[0] + '"' + (o[0] === st.unit_status ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
            }).join('') + '</select></div>';
        }).join('');
      }).join('');
      return head + projects + '<div class="uzb-note"><b style="color:var(--ink)">' + esc(t('r_stages')) + '</b><br>' +
        esc(t('r_stages_hint')) + '</div>' + stages + '</section>';
    }

    function readStages($holder) {
      var out = {};
      $holder.find('[data-stage]').each(function () {
        var pl = $(this).attr('data-stage-pipe');
        (out[pl] = out[pl] || {})[$(this).attr('data-stage')] = $(this).val();
      });
      return out;
    }

    function settingsPage($holder, data, message, isError) {
      var vars = data.vars;
      // Each merchant account of the company; one per provider can be on (a radio in switch form).
      var providers = data.providers.map(function (p) {
        if (!p.accounts.length) {
          return '<div class="uzb-item"><div class="uzb-grow"><div><b>' + esc(p.name) + '</b></div></div>' +
            '<span class="uzb-pill p-off">' + esc(t('s_not_set')) + '</span>' + toggle('uzb-p-' + p.code, false, true) + '</div>';
        }
        return p.accounts.map(function (a) {
          var pill = a.active
            ? '<span class="uzb-pill p-on">' + esc(t('s_active')) + '</span>'
            : '<span class="uzb-pill p-off">' + esc(a.configured ? t('s_disabled') : t('s_not_set')) + '</span>';
          var name = a.name === p.name ? '<b>' + esc(p.name) + '</b>' : '<b>' + esc(p.name) + '</b> · ' + esc(a.name);
          return '<div class="uzb-item"><div class="uzb-grow"><div>' + name + '</div></div>' + pill +
            toggle('uzb-a-' + a.id, a.use, !a.active, ' data-account="' + a.id + '" data-kind="' + esc(p.code) + '"') + '</div>';
        }).join('');
      }).join('');
      var bills = '<div class="uzb-item"><div class="uzb-grow"><div><b>' + esc(t('s_bills')) + '</b></div>' +
        '<div class="uzb-meta">' + esc(t('s_bills_hint')) + '</div></div>' + toggle('uzb-bills', data.bills_enabled, false) + '</div>';

      var sms;
      if (!data.sms.ready) {
        sms = '<div class="uzb-note">' + esc(t('s_sms_missing')) + '</div>';
      } else {
        var usable = data.sms.accounts.filter(function (a) { return a.active; });
        sms = '<div class="uzb-item"><div class="uzb-grow"><div><b>' + esc(t('s_sms_on')) + '</b></div>' +
          '<div class="uzb-meta">' + esc(data.sms.provider) + '</div></div>' + toggle('uzb-sms', data.sms.enabled, false) + '</div>';
        if (usable.length > 1) {
          sms += '<div class="uzb-item"><div class="uzb-grow"><div><b>' + esc(t('s_sms_account')) + '</b></div>' +
            '<div class="uzb-meta">' + esc(t('s_sms_account_hint')) + '</div></div>' +
            '<select id="uzb-sms-acc" style="width:auto;min-width:180px">' + usable.map(function (a) {
              return '<option value="' + a.id + '"' + (a.id === data.sms.account_id ? ' selected' : '') + '>' + esc(a.name) + '</option>';
            }).join('') + '</select></div>';
        }
      }

      var tpls = '';
      if (data.sms.ready) {
        tpls = data.templates.length
          ? data.templates.map(function (tp) {
              var pill = tp.approved ? '' : '<span class="uzb-pill p-bad">' + esc(t('s_not_approved')) + '</span>';
              return '<div class="uzb-item"><div class="uzb-grow"><div title="' + esc(tp.text) + '">' + esc(short(tp.text, 110)) + '</div></div>' +
                pill + toggle('uzb-t-' + tp.id, tp.approved && tp.use, !tp.approved || !data.sms.enabled, ' data-template="' + tp.id + '"') + '</div>';
            }).join('')
          : '<div class="uzb-note">' + esc(t('sms_none')) + '</div>';
      }

      var anyPay = data.providers.some(function (p) { return p.accounts.some(function (a) { return a.configured; }); });
      var panes = [];
      if (anyPay) {
        panes.push(['pay', t('tab_pay'), null,
          '<section class="uzb-card"><div class="uzb-card-h"><b>' + esc(t('s_pay')) + '</b><p>' + esc(t('s_pay_hint')) + '</p></div>' +
          providers + bills + '</section>',
          data.providers.some(function (p) { return p.accounts.some(function (a) { return a.use; }); })]);
      }
      if (data.sms.ready) {
        panes.push(['sms', 'SMS', null,
          '<section class="uzb-card"><div class="uzb-card-h"><b>SMS</b><p>' + esc(t('s_sms_hint')) + '</p></div>' + sms + '</section>' +
          '<section class="uzb-card"><div class="uzb-card-h"><b>' + esc(t('s_tpl')) + '</b><p>' + esc(t('s_tpl_hint')) + '</p></div>' + tpls + '</section>' +
          (vars ? varsSection(vars) : ''),
          data.sms.enabled]);
      }
      if (data.docs.templates.length) {
        panes.push(['docs', t('tab_docs'), null, docsSection(data.docs, data.dashboard), data.docs.enabled]);
      }
      if (data.realty && data.realty.projects.length) {
        panes.push(['realty', t('r_title'), null, realtySection(data.realty, data.dashboard),
          data.realty.projects.some(function (p) { return p.use; })]);
      }
      if (anyPay || data.sms.ready) {
        panes.push(['auto', t('tab_auto'), null,
          '<section class="uzb-card"><div class="uzb-card-h"><b>' + esc(t('s_auto')) + '</b><p>' + esc(t('s_auto_hint')) + '</p></div>' +
          '<ol><li>' + esc(t('s_auto_1')) + '</li><li>' + esc(t('s_auto_2')) + '</li><li>' + esc(t('s_auto_3')) + '</li></ol></section>',
          null]);
      }
      var keys = panes.map(function (x) { return x[0]; });
      if (keys.indexOf(state.settingsTab) < 0) state.settingsTab = keys[0];
      var tabsHtml = panes.length > 1
        ? '<nav class="uzb-ptabs">' + panes.map(function (x) {
            var dot = x[4] === null ? '' : '<i class="' + (x[4] ? 'on' : '') + '"></i>';
            return '<button type="button" class="uzb-ptab' + (x[0] === state.settingsTab ? ' on' : '') + '" data-ptab="' + x[0] + '">' + esc(x[1]) + dot + '</button>';
          }).join('') + '</nav>'
        : '';
      var body = panes.length
        ? panes.map(function (x) {
            return '<div data-pane="' + x[0] + '"' + (x[0] === state.settingsTab ? '' : ' hidden') + '>' + x[3] + '</div>';
          }).join('')
        : '<section class="uzb-card"><div class="uzb-note">' + esc(t('s_nothing')) + '</div></section>';

      $holder.html(
        '<div class="uzb uzb-page' + theme() + '">' +
        '<div class="uzb-head"><div><h2>uzbridge</h2><div class="uzb-meta">' + esc(data.company) + ' · ' + esc(data.account || '') + '</div></div>' +
        '<a href="' + esc(data.dashboard) + '" target="_blank" rel="noopener">' + esc(t('s_dashboard')) + ' ↗</a></div>' +
        tabsHtml +
        (panes.length && panes.length < 5
          ? '<p class="uzb-more">' + esc(t('s_more')) + ' <a href="' + esc(data.dashboard) + '" target="_blank" rel="noopener">' + esc(t('s_dashboard')) + ' ↗</a></p>'
          : '') +
        body +
        (panes.length
          ? '<div class="uzb-save"><button class="uzb-btn" id="uzb-s-save">' + esc(t('s_save')) + '</button>' +
            (message ? '<div class="uzb-msg' + (isError ? ' uzb-err' : ' uzb-okmsg') + '">' + esc(message) + '</div>' : '') + '</div>'
          : '') +
        '</div>'
      );

      $holder.off('.uzbs')
        .on('click.uzbs', '[data-ptab]', function () {
          state.settingsTab = $(this).attr('data-ptab');
          $holder.find('[data-ptab]').removeClass('on');
          $(this).addClass('on');
          $holder.find('[data-pane]').attr('hidden', true);
          $holder.find('[data-pane="' + state.settingsTab + '"]').removeAttr('hidden');
        })
        .on('change.uzbs', '[data-account]', function () {
          // one cash desk per provider: switching one on switches its siblings off
          if (!$(this).prop('checked')) return;
          var me = this;
          $holder.find('[data-kind="' + $(this).attr('data-kind') + '"]').each(function () {
            if (this !== me) $(this).prop('checked', false);
          });
        })
        .on('change.uzbs', '#uzb-docs', function () {
          $holder.find('[data-doc-template]').prop('disabled', !$(this).prop('checked'));
        })
        .on('change.uzbs', '#uzb-sms', function () {
          $holder.find('[data-template]').each(function () {
            var tp = data.templates.filter(function (x) { return String(x.id) === $(this).attr('data-template'); }, this)[0];
            $(this).prop('disabled', !$('#uzb-sms').prop('checked') || !(tp && tp.approved));
          });
        })
        .on('click.uzbs', '#uzb-var-add', function () {
          $('#uzb-var-rows').append(varRow({ key: '', source: '' }, vars.sources));
        })
        .on('click.uzbs', '[data-var-del]', function () {
          $(this).closest('.uzb-var').remove();
        })
        .on('input.uzbs', '[data-var-key]', function () {
          var v = $(this).val().toLowerCase().replace(/[^a-z0-9_]/g, '');
          if (v !== $(this).val()) $(this).val(v);
        })
        .on('click.uzbs', '#uzb-s-save', function () {
          var btn = $(this).prop('disabled', true);
          var rows = vars ? readVars($holder) : null;
          var templates = {};
          $holder.find('[data-template]').each(function () {
            templates[$(this).attr('data-template')] = $(this).prop('checked');
          });
          call('PUT', '/settings', {
            accounts: $holder.find('[data-account]:checked').map(function () { return Number($(this).attr('data-account')); }).get(),
            sms_enabled: data.sms.ready ? $('#uzb-sms').prop('checked') : data.sms.enabled,
            sms_account_id: $('#uzb-sms-acc').length ? Number($('#uzb-sms-acc').val()) : null,
            bills_enabled: $('#uzb-bills').length ? $('#uzb-bills').prop('checked') : data.bills_enabled,
            docs_enabled: $('#uzb-docs').length ? $('#uzb-docs').prop('checked') : data.docs.enabled,
            doc_templates: $holder.find('[data-doc-template]').get().reduce(function (acc, el) {
              acc[$(el).attr('data-doc-template')] = $(el).prop('checked');
              return acc;
            }, {}),
            templates: templates,
            realty_projects: $holder.find('[data-realty-project]').get().reduce(function (acc, el) {
              acc[$(el).attr('data-realty-project')] = $(el).prop('checked');
              return acc;
            }, {}),
            realty_stages: data.realty && data.realty.pipelines.length ? readStages($holder) : null
          })
            .then(function (fresh) {
              if (!rows) return $.Deferred().resolve(fresh, null).promise();
              return call('PUT', '/variables', rows).then(function (v) { return $.Deferred().resolve(fresh, v).promise(); });
            })
            .done(function (fresh, v) {
              fresh.vars = v || vars;
              settingsPage($holder, fresh, t('s_saved'));
            })
            .fail(function (xhr) {
              btn.prop('disabled', false);
              // keep what was typed: re-read the unsaved rows into the page
              if (vars && rows) data.vars = $.extend({}, vars, { variables: rows });
              settingsPage($holder, data, errorText(xhr), true);
            });
        });
    }

    function openSettings() {
      css();
      var $holder = $('#list_page_holder');
      $holder.html('<div class="uzb uzb-page' + theme() + '"><p class="uzb-empty">…</p></div>');
      // The {keywords} list reads amoCRM's fields; if that fails the rest of the page still opens.
      var vars = $.Deferred();
      call('GET', '/variables').done(function (v) { vars.resolve(v); }).fail(function () { vars.resolve(null); });
      $.when(call('GET', '/settings'), vars)
        .done(function (a, v) {
          var data = a[0];
          data.vars = v;
          settingsPage($holder, data);
        })
        .fail(function (xhr) {
          $holder.html('<div class="uzb uzb-page' + theme() + '"><div class="uzb-msg uzb-err">' + esc(errorText(xhr)) + '</div></div>');
        });
    }

    // ---------------------------------------------------------------- digital pipeline

    function delayLabel(m) {
      if (!m) return t('dp_now');
      if (m < 60) return m + ' ' + t('dp_min');
      if (m < 1440) return (m / 60) + ' ' + t('dp_hour');
      return (m / 1440) + ' ' + t('dp_day');
    }

    // amoCRM renders our dp.settings as plain text inputs; hide them and put
    // real controls on top that write back into them, so amoCRM saves the values.
    function dpForm() {
      css();
      var $inputs = $('input[name="uzb_action"]');
      if (!$inputs.length) return;
      // The nearest ancestor holding all four of our fields is this trigger's form.
      var $form = $inputs.last().parent();
      while ($form.length && !$form.find('input[name="uzb_key"]').length) $form = $form.parent();
      var get = function (name) { return $form.find('input[name="' + name + '"]'); };
      if ($form.find('.uzb-dp').length) return;
      $.each(['uzb_action', 'uzb_template', 'uzb_delay', 'uzb_key'], function (_, n) {
        var $i = get(n);
        var $row = $i.closest('.widget_settings_block__item_field, .digital-pipeline__field, .widget_settings_block__item');
        ($row.length ? $row : $i).hide();
      });
      var $box = $('<div class="uzb uzb-dp' + theme() + '"><p class="uzb-empty">…</p></div>');
      get('uzb_action').closest('.widget_settings_block__item_field, .digital-pipeline__field, .widget_settings_block__item').first().before($box);
      if (!$box.parent().length) get('uzb_action').before($box);

      call('GET', '/settings')
        .done(function (data) {
          get('uzb_key').val(data.dp_key).trigger('change');
          var payOn = data.providers.some(function (p) { return p.accounts.some(function (a) { return a.use; }); });
          var smsOn = data.sms.ready && data.sms.enabled;
          var usable = data.templates.filter(function (x) { return x.approved && x.use; });
          var actions = [];
          if (payOn) actions.push(['link', t('dp_link')]);
          if (smsOn && usable.length) actions.push(['sms', t('dp_sms')]);
          if (payOn && smsOn && usable.length) actions.push(['link_sms', t('dp_link_sms')]);
          if (!actions.length) {
            $box.html('<div class="uzb-msg">' + esc(t('nothing_on')) + '</div>');
            return;
          }
          var cur = get('uzb_action').val() || actions[0][0];
          var opt = function (list, val) {
            return list.map(function (a) {
              return '<option value="' + esc(a[0]) + '"' + (String(a[0]) === String(val) ? ' selected' : '') + '>' + esc(a[1]) + '</option>';
            }).join('');
          };
          $box.html(
            '<label>' + esc(t('dp_action')) + '</label><select id="uzb-dp-action">' + opt(actions, cur) + '</select>' +
            '<div id="uzb-dp-tplrow"><label>' + esc(t('sms_pick')) + '</label><select id="uzb-dp-tpl">' +
            opt(usable.map(function (x) { return [x.id, short(x.text, 60)]; }), get('uzb_template').val()) + '</select></div>' +
            '<label>' + esc(t('dp_when')) + '</label><select id="uzb-dp-delay">' +
            opt(DELAYS.map(function (m) { return [m, m ? t('dp_after') + ' ' + delayLabel(m) : delayLabel(0)]; }), get('uzb_delay').val() || 0) +
            '</select><div class="uzb-meta" style="margin-top:8px">' + esc(t('dp_hint')) + '</div>'
          );
          var sync = function () {
            var a = $('#uzb-dp-action').val();
            $('#uzb-dp-tplrow').toggle(a !== 'link');
            get('uzb_action').val(a).trigger('change');
            get('uzb_template').val(a === 'link' ? '' : $('#uzb-dp-tpl').val()).trigger('change');
            get('uzb_delay').val($('#uzb-dp-delay').val()).trigger('change');
          };
          $box.on('change', 'select', sync);
          sync();
        })
        .fail(function (xhr) {
          $box.html('<div class="uzb-msg uzb-err">' + esc(errorText(xhr)) + '</div>');
        });
    }

    // ---------------------------------------------------------------- callbacks

    this.callbacks = {
      settings: function () {
        return true;
      },
      init: function () {
        css();
        // SMS as a feed source: amoCRM offers it for the card's phone numbers
        // and in the note/chat control at the bottom of the card.
        if (typeof self.add_source === 'function') {
          self.add_source('sms', function (params) {
            return new Promise(function (resolve, reject) {
              call('POST', '/sms', {
                phone: String(params.phone),
                message: params.message,
                contact_id: params.contact_id || null,
                lead_id: leadId() || null
              })
                .done(function (res) { resolve(res); })
                .fail(function (xhr) { reject(new Error(errorText(xhr))); });
            });
          });
        }
        return true;
      },
      render: function () {
        if (self.system().area !== 'lcard') return true; // contact/company cards: only the SMS source
        self.render_template({
          caption: { class_name: 'uzb-caption', html: 'uzbridge' },
          body: '',
          render: '<div id="uzb-root"></div>'
        });
        load();
        return true;
      },
      advancedSettings: function () {
        openSettings();
        return true;
      },
      dpSettings: function () {
        dpForm();
        setTimeout(dpForm, 300); // the trigger form can render after this callback
        return true;
      },
      bind_actions: function () {
        $(document)
          .off('.uzb')
          .on('click.uzb', '#uzb-root [data-tab]', function () {
            state.tab = $(this).attr('data-tab');
            if (state.ctx) paint(state.ctx);
          })
          .on('click.uzb', '#uzb-showroom', function () {
            openShowroom();
          })
          .on('click.uzb', '#uzb-card-reload', function (e) {
            e.preventDefault();
            window.location.reload();
          })
          .on('click.uzb', '[data-unit-detach]', function () {
            if (!window.confirm(t('r_detach_confirm'))) return;
            $(this).prop('disabled', true);
            call('POST', '/realty/detach', { lead_id: state.leadId, unit_id: Number($(this).attr('data-unit-detach')) })
              .done(function (res) {
                state.realty = res;
                state.realtyChanged = true;
                paint(state.ctx, esc(t('r_detached')));
              })
              .fail(function (xhr) { paint(state.ctx, esc(errorText(xhr)), true); });
          })
          .on('change.uzb', '#uzb-doc-tpl', function () {
            state.docTpl = Number($(this).val());
            state.docFmt = null;
            paint(state.ctx);
          })
          .on('click.uzb', '[data-doc-format]', function () {
            state.docFmt = $(this).attr('data-doc-format');
            paint(state.ctx);
          })
          .on('click.uzb', '#uzb-doc-gen, [data-doc-regen]', function () {
            var regen = $(this).attr('data-doc-regen');
            var tplId = regen ? Number(regen) : state.docTpl;
            var fmt = regen ? $(this).attr('data-doc-fmt') : (state.docFmt || '');
            state.busy = true;
            paint(state.ctx);
            call('POST', '/docs/generate', { lead_id: state.leadId, template_id: tplId, format: fmt, user_name: userName() })
              .done(function (res) {
                state.busy = false;
                state.docs = res;
                paint(state.ctx, esc(t('d_ready')) + ' № ' + esc(res.made.number) +
                  ' — <a href="' + esc(res.made.url) + '" target="_blank" rel="noopener">' + esc(t('d_open')) + '</a>');
              })
              .fail(function (xhr) {
                state.busy = false;
                paint(state.ctx, esc(errorText(xhr)), true);
              });
          })
          .on('change.uzb', '#uzb-sms-tpl', function () {
            var id = Number($(this).val());
            var tpl = (state.ctx && state.ctx.sms_templates || []).filter(function (x) { return x.id === id; })[0];
            $('#uzb-sms-preview').text(tpl ? tpl.text : '');
          })
          .on('click.uzb', '#uzb-create', function () {
            var amount = $('#uzb-amount').val();
            if (!amount) return;
            state.busy = true;
            $(this).prop('disabled', true);
            call('POST', '/invoices', {
              lead_id: state.leadId,
              amount: String(amount),
              description: $('#uzb-desc').val() || '',
              lead_name: leadName(),
              user_name: userName()
            })
              .done(function () {
                state.busy = false;
                load(t('created'));
              })
              .fail(function (xhr) {
                state.busy = false;
                load(errorText(xhr), true);
              });
          })
          .on('click.uzb', '[data-copy]', function () {
            var btn = $(this);
            var text = btn.attr('data-copy');
            var done = function () {
              btn.text(t('copied'));
              setTimeout(function () { btn.text(t('copy')); }, 1500);
            };
            if (navigator.clipboard) {
              navigator.clipboard.writeText(text).then(done, function () { btn.prevAll('input').select(); });
            } else {
              btn.prevAll('input').select();
            }
          })
          .on('click.uzb', '#uzb-sms-send', function () {
            var btn = $(this);
            btn.prop('disabled', true);
            call('POST', '/sms/template', { lead_id: state.leadId, template_id: Number($('#uzb-sms-tpl').val()) })
              .done(function (res) { load(t('sms_sent') + ' +' + res.phone); })
              .fail(function (xhr) { load(errorText(xhr), true); });
          })
          .on('click.uzb', '[data-cancel]', function () {
            call('POST', '/invoices/' + $(this).attr('data-cancel') + '/cancel')
              .done(function () { load(); })
              .fail(function (xhr) { load(errorText(xhr), true); });
          });
        return true;
      },
      onSave: function () {
        return true;
      },
      destroy: function () {
        $(document).off('.uzb');
        $('.uzb-sr').remove();
      }
    };
    return this;
  };

  return Widget;
});
