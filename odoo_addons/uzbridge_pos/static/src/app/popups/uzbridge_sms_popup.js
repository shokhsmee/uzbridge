import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";

/** Send the customer an approved SMS template, keywords (link, amount, ...) filled in. */
export class UzbridgeSmsPopup extends Component {
    static template = "uzbridge_pos.UzbridgeSmsPopup";
    static components = { Dialog };
    static props = { pos: Object, orderId: Number, phone: { type: String, optional: true }, close: Function };

    setup() {
        this.state = useState({
            phone: this.props.phone || "",
            templates: [],
            templateId: null,
            preview: "",
            error: "",
            sending: false,
            sent: false,
        });
        onWillStart(async () => {
            try {
                const templates = await this.call("uzbridge_sms_templates", []);
                this.state.templates = templates;
                // A template with {link} first: that's what the till usually wants to send.
                const pick = templates.find((t) => t.has_link) || templates[0];
                if (pick) {
                    await this.select(pick.id);
                }
            } catch (e) {
                this.state.error = this.message(e);
            }
        });
    }

    call(method, args) {
        const ids = method === "uzbridge_sms_templates" ? [] : [[this.props.orderId]];
        return this.props.pos.data.call("pos.order", method, [...ids, ...args]);
    }

    message(e) {
        return e?.data?.message || e?.message || _t("Something went wrong.");
    }

    async select(id) {
        this.state.templateId = Number(id);
        this.state.error = "";
        try {
            this.state.preview = await this.call("uzbridge_sms_preview", [this.state.templateId]);
        } catch (e) {
            this.state.preview = "";
            this.state.error = this.message(e);
        }
    }

    async send() {
        const digits = this.state.phone.replace(/\D/g, "");
        if (digits.length < 9) {
            this.state.error = _t("Enter the customer's phone number.");
            return;
        }
        if (!this.state.templateId) {
            this.state.error = _t("Pick an SMS template.");
            return;
        }
        this.state.sending = true;
        this.state.error = "";
        try {
            await this.call("uzbridge_send_sms", [this.state.phone, this.state.templateId]);
            this.state.sent = true;
            setTimeout(() => this.props.close(), 1200);
        } catch (e) {
            this.state.error = this.message(e);
        } finally {
            this.state.sending = false;
        }
    }
}
