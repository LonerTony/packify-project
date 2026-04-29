/**
 * settlement.js
 * Handles settlement form submission and backend API interaction.
 */

document.addEventListener("DOMContentLoaded", function () {
    const settlementForm = document.getElementById("settlement-form");
    const messageArea = document.getElementById("message-area");
    const errorArea = document.getElementById("settlement-error");

    if (!settlementForm) {
        console.error("Settlement form not found.");
        return;
    }

    settlementForm.addEventListener("submit", async function (e) {
        e.preventDefault();

        if (messageArea) messageArea.innerHTML = "";
        if (errorArea) errorArea.innerText = "";

        const orderIdElement =
            document.getElementById("order-id") ||
            document.getElementById("orderId");

        const amountElement =
            document.getElementById("settlement-amount") ||
            document.getElementById("amount");

        const orderId = orderIdElement ? orderIdElement.value.trim() : "";
        const settlementAmount = amountElement
            ? parseFloat(String(amountElement.value).replace(/[^0-9.]/g, ""))
            : NaN;

        if (!orderId) {
            if (errorArea) errorArea.innerText = "Order ID is required.";
            return;
        }

        if (Number.isNaN(settlementAmount) || settlementAmount <= 0) {
            if (errorArea) errorArea.innerText = "Settlement amount must be greater than 0.";
            return;
        }

        try {
            const response = await fetch("/settlement", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    order_id: orderId,
                    settlement_amount: settlementAmount
                })
            });

            const result = await response.json();

            if (!response.ok) {
                if (errorArea) {
                    errorArea.innerText = result.message || "Settlement failed.";
                }
                return;
            }

            if (messageArea) {
                messageArea.innerHTML = `
                    <p class="success">
                        ${result.message || "Settlement completed successfully."}
                    </p>
                `;
            }

            settlementForm.reset();
        } catch (err) {
            console.error("Settlement error:", err);
            if (errorArea) {
                errorArea.innerText = "Settlement service temporarily unavailable.";
            }
        }
    });
});