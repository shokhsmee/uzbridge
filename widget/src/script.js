/*
 * uzbridge amoCRM widget: payment links in the lead card (right column).
 *
 * Every call goes through self.$authorizedAjax, which adds an X-Auth-Token
 * JWT signed with our integration's client secret; the backend maps its
 * account_id to the company. __API_BASE__ is replaced by build.py.
 */
define(['jquery'], function ($) {
  var API = '__API_BASE__';

  var CSS = [
    '.uzb{font-size:13px;line-height:1.45;color:#14201f}',
    '.uzb label{display:block;font-size:12px;color:#5b6765;margin:8px 0 4px}',
    '.uzb input{width:100%;box-sizing:border-box;height:32px;border:1px solid #dde3e2;border-radius:6px;padding:0 8px;font-size:13px}',
    '.uzb input:focus{border-color:#12877f;outline:none}',
    '.uzb .uzb-btn{margin-top:10px;width:100%;height:34px;border:0;border-radius:6px;background:#12877f;color:#fff;font-weight:600;cursor:pointer}',
    '.uzb .uzb-btn[disabled]{opacity:.5;cursor:default}',
    '.uzb .uzb-msg{margin-top:8px;padding:6px 8px;border-radius:6px;background:#f7eed8;color:#9a6a00}',
    '.uzb .uzb-err{background:#f7e3df;color:#a33b2b}',
    '.uzb h4{margin:16px 0 6px;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#5b6765;font-weight:500}',
    '.uzb .uzb-inv{border:1px solid #dde3e2;border-radius:6px;padding:8px;margin-bottom:6px}',
    '.uzb .uzb-row{display:flex;justify-content:space-between;align-items:center;gap:6px}',
    '.uzb .uzb-amt{font-weight:600;font-variant-numeric:tabular-nums}',
    '.uzb .uzb-pill{font-size:11px;padding:2px 7px;border-radius:99px;white-space:nowrap}',
    '.uzb .p-pending{background:#f7eed8;color:#9a6a00}.uzb .p-paid{background:#e3f2e7;color:#1d7a3a}',
    '.uzb .p-cancelled{background:#eef1f1;color:#5b6765}.uzb .p-refunded{background:#f7e3df;color:#a33b2b}',
    '.uzb .uzb-link{display:flex;gap:4px;margin-top:6px}',
    '.uzb .uzb-link input{height:28px;font-size:11px;background:#f3f5f5}',
    '.uzb .uzb-mini{height:28px;border:1px solid #dde3e2;background:#fff;border-radius:6px;padding:0 8px;cursor:pointer;font-size:12px;white-space:nowrap}',
    '.uzb .uzb-meta{font-size:11px;color:#5b6765;margin-top:2px}'
  ].join('');

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  var Widget = function () {
    var self = this;
    var state = { leadId: 0, busy: false };

    function t(key) {
      return self.i18n('ui')[key] || key;
    }

    function leadId() {
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

    function $root() {
      return $('#uzb-root');
    }

    function renderInvoices(invoices) {
      if (!invoices.length) return '<p class="uzb-meta">' + esc(t('empty')) + '</p>';
      return invoices
        .map(function (inv) {
          var link =
            inv.status === 'pending'
              ? '<div class="uzb-link"><input readonly value="' + esc(inv.url) + '">' +
                '<button class="uzb-mini" data-copy="' + esc(inv.url) + '">' + esc(t('copy')) + '</button>' +
                '<button class="uzb-mini" data-cancel="' + esc(inv.id) + '">✕</button></div>'
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

    function paint(ctx, message, isError) {
      var noProviders = ctx && !ctx.providers.length;
      var html =
        '<div class="uzb">' +
        '<label for="uzb-amount">' + esc(t('amount')) + '</label>' +
        '<input id="uzb-amount" inputmode="decimal" value="' + esc(leadPrice()) + '">' +
        '<label for="uzb-desc">' + esc(t('description')) + '</label>' +
        '<input id="uzb-desc" maxlength="255">' +
        '<button class="uzb-btn" id="uzb-create"' + (noProviders || state.busy ? ' disabled' : '') + '>' + esc(t('create')) + '</button>' +
        (noProviders ? '<div class="uzb-msg">' + esc(t('no_providers')) + '</div>' : '') +
        (message ? '<div class="uzb-msg' + (isError ? ' uzb-err' : '') + '">' + esc(message) + '</div>' : '') +
        '<h4>' + esc(t('history')) + '</h4>' +
        '<div id="uzb-list">' + (ctx ? renderInvoices(ctx.invoices) : '') + '</div>' +
        '</div>';
      $root().html(html);
    }

    function load(message, isError) {
      state.leadId = leadId();
      if (!state.leadId) {
        $root().html('<div class="uzb"><p class="uzb-meta">' + esc(t('save_lead_first')) + '</p></div>');
        return;
      }
      call('GET', '/context?lead_id=' + state.leadId)
        .done(function (ctx) {
          paint(ctx, message, isError);
        })
        .fail(function (xhr) {
          $root().html('<div class="uzb"><div class="uzb-msg uzb-err">' + esc(errorText(xhr)) + '</div></div>');
        });
    }

    this.callbacks = {
      settings: function () {
        return true;
      },
      init: function () {
        if (!document.getElementById('uzb-css')) {
          $('head').append('<style id="uzb-css">' + CSS + '</style>');
        }
        return true;
      },
      render: function () {
        if (self.system().area !== 'lcard') return true;
        self.render_template({
          caption: { class_name: 'uzb-caption' },
          body: '',
          render: '<div id="uzb-root"></div>'
        });
        load();
        return true;
      },
      bind_actions: function () {
        $(document)
          .off('.uzb')
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
                load();
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
              navigator.clipboard.writeText(text).then(done, function () { btn.prev('input').select(); });
            } else {
              btn.prev('input').select();
            }
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
