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
    '.uzb-dp{padding:4px 0 8px}.uzb-dp > label:first-child{margin-top:0}'
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
    var state = { leadId: 0, busy: false, tab: 'pay', ctx: null };

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

    function css() {
      if (!document.getElementById('uzb-css')) $('head').append('<style id="uzb-css">' + CSS + '</style>');
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

    function paint(ctx, message, isError) {
      var pay = ctx.providers.length > 0;
      var sms = ctx.sms_ready;
      if (!pay && sms) state.tab = 'sms';
      if (pay && !sms) state.tab = 'pay';
      var html = '<div class="uzb' + theme() + '">' +
        '<div class="uzb-meta" style="margin:0 0 8px">uzbridge · <b style="color:var(--ink)">' + esc(ctx.company) + '</b></div>';
      if (!pay && !sms) {
        html += '<div class="uzb-msg">' + esc(t('nothing_on')) + '</div>';
      } else {
        if (pay && sms) {
          html += '<div class="uzb-tabs">' +
            '<button class="uzb-tab' + (state.tab === 'pay' ? ' on' : '') + '" data-tab="pay">' + esc(t('tab_pay')) + '</button>' +
            '<button class="uzb-tab' + (state.tab === 'sms' ? ' on' : '') + '" data-tab="sms">' + esc(t('tab_sms')) + '</button></div>';
        }
        if (message) html += '<div class="uzb-msg' + (isError ? ' uzb-err' : ' uzb-okmsg') + '">' + esc(message) + '</div>';
        html += state.tab === 'sms' ? smsPane(ctx) : payPane(ctx);
      }
      $root().html(html + '</div>');
    }

    function load(message, isError) {
      state.leadId = leadId();
      if (!state.leadId) {
        $root().html('<div class="uzb' + theme() + '"><p class="uzb-empty">' + esc(t('save_lead_first')) + '</p></div>');
        return;
      }
      call('GET', '/context?lead_id=' + state.leadId)
        .done(function (ctx) {
          state.ctx = ctx;
          paint(ctx, message, isError);
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

      $holder.html(
        '<div class="uzb uzb-page' + theme() + '">' +
        '<div class="uzb-head"><div><h2>uzbridge</h2><div class="uzb-meta">' + esc(data.company) + ' · ' + esc(data.account || '') + '</div></div>' +
        '<a href="' + esc(data.dashboard) + '" target="_blank" rel="noopener">' + esc(t('s_dashboard')) + ' ↗</a></div>' +

        '<section class="uzb-card"><div class="uzb-card-h"><b>' + esc(t('s_pay')) + '</b><p>' + esc(t('s_pay_hint')) + '</p></div>' +
        providers + bills + '</section>' +

        '<section class="uzb-card"><div class="uzb-card-h"><b>SMS</b><p>' + esc(t('s_sms_hint')) + '</p></div>' + sms + '</section>' +

        (data.sms.ready
          ? '<section class="uzb-card"><div class="uzb-card-h"><b>' + esc(t('s_tpl')) + '</b><p>' + esc(t('s_tpl_hint')) + '</p></div>' + tpls + '</section>'
          : '') +
        (data.sms.ready && vars ? varsSection(vars) : '') +

        '<section class="uzb-card"><div class="uzb-card-h"><b>' + esc(t('s_auto')) + '</b><p>' + esc(t('s_auto_hint')) + '</p></div>' +
        '<ol><li>' + esc(t('s_auto_1')) + '</li><li>' + esc(t('s_auto_2')) + '</li><li>' + esc(t('s_auto_3')) + '</li></ol></section>' +

        '<div class="uzb-save"><button class="uzb-btn" id="uzb-s-save">' + esc(t('s_save')) + '</button>' +
        (message ? '<div class="uzb-msg' + (isError ? ' uzb-err' : ' uzb-okmsg') + '">' + esc(message) + '</div>' : '') +
        '</div></div>'
      );

      $holder.off('.uzbs')
        .on('change.uzbs', '[data-account]', function () {
          // one cash desk per provider: switching one on switches its siblings off
          if (!$(this).prop('checked')) return;
          var me = this;
          $holder.find('[data-kind="' + $(this).attr('data-kind') + '"]').each(function () {
            if (this !== me) $(this).prop('checked', false);
          });
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
            bills_enabled: $('#uzb-bills').prop('checked'),
            templates: templates
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
      $.when(call('GET', '/settings'), call('GET', '/variables'))
        .done(function (a, b) {
          var data = a[0];
          data.vars = b[0];
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
      }
    };
    return this;
  };

  return Widget;
});
