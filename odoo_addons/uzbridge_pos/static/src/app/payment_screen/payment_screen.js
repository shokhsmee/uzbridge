import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { UzbridgeLinkPopup } from "../popups/uzbridge_link_popup";
import { UzbridgeSmsPopup } from "../popups/uzbridge_sms_popup";

patch(PaymentScreen.prototype, {
    /** The server needs the order (and its id) before a link or SMS can point at it. */
    async uzbridgeSyncedOrder() {
        const order = this.currentOrder;
        await this.pos.syncAllOrders({ orders: [order] });
        if (typeof order.id !== "number") {
            this.dialog.add(AlertDialog, {
                title: _t("Not saved yet"),
                body: _t("The order couldn't be saved to the server. Check the connection and try again."),
            });
            return null;
        }
        return order;
    },

    async uzbridgeShowLink() {
        const order = await this.uzbridgeSyncedOrder();
        if (!order) {
            return;
        }
        try {
            const link = await this.pos.data.call("pos.order", "uzbridge_payment_link", [[order.id]]);
            this.dialog.add(UzbridgeLinkPopup, {
                link,
                formattedAmount: this.env.utils.formatCurrency(order.remainingDue || order.totalDue),
                orderName: order.pos_reference || order.name || "",
            });
        } catch (e) {
            this.dialog.add(AlertDialog, { title: _t("Payment link"), body: e?.data?.message || String(e) });
        }
    },

    async uzbridgeSendSms() {
        const order = await this.uzbridgeSyncedOrder();
        if (!order) {
            return;
        }
        this.dialog.add(UzbridgeSmsPopup, {
            pos: this.pos,
            orderId: order.id,
            phone: order.getPartner()?.phone || order.getPartner()?.mobile || "",
        });
    },
});
