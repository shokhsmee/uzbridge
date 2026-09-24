import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { qrCodeSrc } from "@point_of_sale/utils";

/** The order's pay link, as text to copy and as a QR the customer can scan. */
export class UzbridgeLinkPopup extends Component {
    static template = "uzbridge_pos.UzbridgeLinkPopup";
    static components = { Dialog };
    static props = { link: String, formattedAmount: String, orderName: String, close: Function };

    setup() {
        this.state = useState({ copied: false });
        this.qr = qrCodeSrc(this.props.link);
    }

    async copy() {
        try {
            await navigator.clipboard.writeText(this.props.link);
            this.state.copied = true;
            setTimeout(() => (this.state.copied = false), 1500);
        } catch {
            this.linkInput?.select?.();
        }
    }
}
