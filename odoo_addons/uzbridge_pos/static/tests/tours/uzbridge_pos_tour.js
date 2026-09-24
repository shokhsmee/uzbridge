import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("UzbridgePosButtonsTour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ProductScreen.addOrderline("Letter Tray", "10"),
            ProductScreen.clickPayButton(),
            {
                content: "open the payment link",
                trigger: ".payment-buttons button:contains('Payment link')",
                run: "click",
            },
            {
                content: "the link has a QR and points at the order's pay page",
                trigger: ".modal-content img[alt='QR code of the payment link']",
            },
            {
                trigger: ".modal-content input.font-monospace:value(/pos/pay/)",
            },
            {
                content: "close it",
                trigger: ".modal-header .btn-close",
                run: "click",
            },
            {
                content: "open send SMS",
                trigger: ".payment-buttons button:contains('Send SMS')",
                run: "click",
            },
            {
                content: "the template preview has the link filled in",
                trigger: ".modal-content .bg-light:contains('/pos/pay/')",
            },
            {
                content: "a too-short number is refused",
                trigger: ".modal-content input[type='tel']",
                run: "edit 12",
            },
            {
                trigger: ".modal-content button.btn-primary:contains('Send SMS')",
                run: "click",
            },
            {
                trigger: ".modal-content .alert-danger:contains('phone')",
            },
            {
                trigger: ".modal-content input[type='tel']",
                run: "edit +998901234567",
            },
            {
                trigger: ".modal-content button.btn-primary:contains('Send SMS')",
                run: "click",
            },
            {
                content: "sent",
                trigger: ".modal-content .alert-success",
            },
        ].flat(),
});
