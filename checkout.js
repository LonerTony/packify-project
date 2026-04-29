/**
 * checkout.js
 * Coordinates checkout submission, live validation, cart clearing, redirect,
 * and field-level payment validation.
 */

document.addEventListener("DOMContentLoaded", function () {
    const checkoutForm = document.getElementById("checkout-form");
    const errorDisplay = document.getElementById("card-error");
    const messageArea = document.getElementById("message-area");

    const submitButton = checkoutForm?.querySelector('button[type="submit"]');

    if (!checkoutForm) {
        console.error("Checkout form not found.");
        return;
    }

    if (submitButton) submitButton.disabled = true;

    function setError(id, message) {
        const el = document.getElementById(id);
        if (el) el.textContent = message || "";
    }

    function clearFieldErrors() {
        setError("card-error", "");
        setError("month-error", "");
        setError("year-error", "");
        setError("cvv-error", "");
        setError("zip-error", "");
    }

    function getNormalizedCartItems() {
        let cartItems = [];

        try {
            cartItems = JSON.parse(localStorage.getItem("cart")) || [];
        } catch (err) {
            console.error("Error reading cart from localStorage:", err);
            cartItems = [];
        }

        if (!Array.isArray(cartItems)) return [];

        return cartItems.map(item => ({
            name: item.name || item.product_name || item.productName || "",
            quantity: parseInt(item.quantity ?? item.qty ?? 1, 10) || 1,
            price: parseFloat(item.price ?? item.unitPrice ?? 0) || 0
        })).filter(item => item.name && item.quantity > 0);
    }

    function getRawAmount() {
        const totalAmountElement = document.getElementById("total-amount");
        return totalAmountElement
            ? totalAmountElement.innerText.replace(/[^0-9.]/g, "")
            : "0";
    }

    function getCurrentFormData() {
        return {
            firstName: document.getElementById("first-name")?.value.trim() || "",
            lastName: document.getElementById("last-name")?.value.trim() || "",
            address: document.getElementById("address")?.value.trim() || "",
            cardNumber: document.getElementById("card-number")?.value.trim() || "",
            month: document.getElementById("month")?.value.trim() || "",
            year: document.getElementById("year")?.value.trim() || "",
            cvv: document.getElementById("cvv")?.value.trim() || "",
            zip: document.getElementById("zip")?.value.trim() || "",
            amount: parseFloat(getRawAmount()) || 0
        };
    }

    function detectCardType(cardNumber) {
        const clean = cardNumber.replace(/\D/g, "");

        if (/^4/.test(clean)) return "Visa";
        if (/^5[1-5]/.test(clean)) return "Mastercard";
        if (/^3[47]/.test(clean)) return "Amex";

        return "Unknown";
    }

    function maskCardNumber(cardNumber) {
        const clean = cardNumber.replace(/\D/g, "");
        if (clean.length < 4) return "";
        return "•••• •••• •••• " + clean.slice(-4);
    }

    function validatePaymentFields(formData, showErrors = true) {
        let valid = true;

        const cleanCard = formData.cardNumber.replace(/\D/g, "");
        const monthNum = Number(formData.month);
        const yearNum = Number(formData.year);
        const cvv = formData.cvv.replace(/\D/g, "");
        const zip = formData.zip.replace(/\D/g, "");

        if (showErrors) clearFieldErrors();

        // Card number
        if (!cleanCard) {
            if (showErrors) setError("card-error", "Card number is required.");
            valid = false;
        } else if (cleanCard.length < 15 || cleanCard.length > 16) {
            if (showErrors) setError("card-error", "Card number must be 15 or 16 digits.");
            valid = false;
        }

        // Month
        if (!formData.month) {
            if (showErrors) setError("month-error", "Month is required.");
            valid = false;
        } else if (!/^\d{2}$/.test(formData.month) || monthNum < 1 || monthNum > 12) {
            if (showErrors) setError("month-error", "Enter a valid month.");
            valid = false;
        }

        // Year
        if (!formData.year) {
            if (showErrors) setError("year-error", "Year is required.");
            valid = false;
        } else if (!/^\d{2}$/.test(formData.year)) {
            if (showErrors) setError("year-error", "Enter a valid 2-digit year.");
            valid = false;
        }

        // Expiration check
        if (/^\d{2}$/.test(formData.month) && /^\d{2}$/.test(formData.year)) {
            const now = new Date();
            const currentYear = now.getFullYear() % 100;
            const currentMonth = now.getMonth() + 1;

            if (yearNum < currentYear || (yearNum === currentYear && monthNum < currentMonth)) {
                if (showErrors) {
                    setError("month-error", "Card is expired.");
                    setError("year-error", "Card is expired.");
                }
                valid = false;
            }
        }

        // CVV
        const cardType = detectCardType(formData.cardNumber);
        const requiredCvvLength = cardType === "Amex" ? 4 : 3;

        if (!cvv) {
            if (showErrors) setError("cvv-error", "CVV is required.");
            valid = false;
        } else if (cvv.length !== requiredCvvLength) {
            if (showErrors) {
                setError("cvv-error", `${cardType === "Amex" ? "Amex" : "Card"} CVV must be ${requiredCvvLength} digits.`);
            }
            valid = false;
        }

        // ZIP
        if (!zip) {
            if (showErrors) setError("zip-error", "ZIP code is required.");
            valid = false;
        } else if (!/^\d{5}$/.test(zip)) {
            if (showErrors) setError("zip-error", "ZIP code must be 5 digits.");
            valid = false;
        }

        return valid;
    }

    function updateCardDisplays(formData) {
        const cardTypeDisplay = document.getElementById("card-type-display");
        const maskedCardDisplay = document.getElementById("masked-card-display");

        const cleanNumber = formData.cardNumber.replace(/\D/g, "");
        const cardType = detectCardType(formData.cardNumber);

        if (cardTypeDisplay) {
            cardTypeDisplay.textContent =
                cleanNumber.length >= 1 && cardType !== "Unknown"
                    ? `Card Type: ${cardType}`
                    : "";
        }

        if (maskedCardDisplay) {
            maskedCardDisplay.textContent =
                cleanNumber.length >= 4
                    ? `Card: ${maskCardNumber(formData.cardNumber)}`
                    : "";
        }
    }

    function runLiveValidation(showErrors = true) {
        const formData = getCurrentFormData();
        const cartItems = getNormalizedCartItems();

        updateCardDisplays(formData);

        let valid = true;

        if (cartItems.length === 0) {
            if (showErrors) setError("card-error", "Your cart is empty.");
            valid = false;
        }

        if (!validatePaymentFields(formData, showErrors)) {
            valid = false;
        }

        // Keep existing full-form validation if validation.js exists
        if (window.Validation && typeof Validation.validateForm === "function") {
            const validationResult = Validation.validateForm(formData);

            if (!validationResult.isValid) {
                valid = false;
            }
        }

        if (submitButton) submitButton.disabled = !valid;

        return valid;
    }

    const liveValidationFields = [
        "first-name",
        "last-name",
        "address",
        "card-number",
        "month",
        "year",
        "cvv",
        "zip"
    ];

    liveValidationFields.forEach(id => {
        const field = document.getElementById(id);

        if (field) {
            field.addEventListener("input", () => runLiveValidation(true));
            field.addEventListener("change", () => runLiveValidation(true));
            field.addEventListener("blur", () => runLiveValidation(true));
        }
    });

    runLiveValidation(false);

    checkoutForm.addEventListener("submit", async function (e) {
        e.preventDefault();

        if (!runLiveValidation(true)) return;

        clearFieldErrors();
        messageArea.innerHTML = "";

        if (submitButton) submitButton.disabled = true;

        const normalizedCartItems = getNormalizedCartItems();

        const formData = {
            ...getCurrentFormData(),
            cartItems: normalizedCartItems
        };

        messageArea.innerHTML = `<p>Processing payment...</p>`;

        try {
            const response = await fetch("/checkout", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify(formData)
            });

            let result;

            try {
                result = await response.json();
            } catch {
                throw new Error("Invalid server response.");
            }

            handleApiResponse(result, messageArea, errorDisplay);

            if (
                response.ok &&
                (result.status === "Authorized" || result.status === "Approved")
            ) {
                localStorage.removeItem("cart");

                messageArea.innerHTML = `
                    <p class="success">
                        Payment Authorized. Order ID: ${result.order_id || "N/A"}. Redirecting to orders...
                    </p>
                `;

                if (submitButton) submitButton.disabled = true;

                setTimeout(() => {
                    window.location.href = "/orders";
                }, 1200);

                return;
            }

            runLiveValidation(false);

        } catch (err) {
            console.error("Checkout error:", err);
            setError("card-error", "Payment service temporarily unavailable.");
            messageArea.innerHTML = "";
            runLiveValidation(false);
        }
    });
});

function handleApiResponse(result, messageArea, errorDisplay) {
    errorDisplay.innerText = "";
    messageArea.innerHTML = "";

    const amount = result.amount || result.authorizedAmount || "0.00";
    const message = result.message || "";

    switch (result.status) {
        case "Authorized":
        case "Approved":
            messageArea.innerHTML = `
                <p class="success">
                    Payment Authorized. Order ID: ${result.order_id || "N/A"}. Amount: $${amount}
                </p>
            `;
            break;

        case "Failed - Incorrect Info":
            messageArea.innerHTML = `<p class="error">Authorization Failed: Incorrect card details.</p>`;
            break;

        case "Failed - Insufficient Funds":
            messageArea.innerHTML = `<p class="error">Authorization Failed: Insufficient funds.</p>`;
            break;

        case "Failed":
            messageArea.innerHTML = `<p class="error">${message || "Authorization Failed."}</p>`;
            break;

        case "Error":
        default:
            messageArea.innerHTML = `<p class="error">${message || "Payment service temporarily unavailable."}</p>`;
            break;
    }
}