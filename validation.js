/**
 * validation.js
 * Handles client-side validation for Packify checkout.
 * - Detects card type
 * - Masks card number
 * - Validates required fields
 * - Validates PAN, expiry, CVV, ZIP, and amount
 */

const Validation = {
    detectCardType(cardNumber) {
        const cleanNumber = String(cardNumber || "").replace(/\D/g, "");

        if (/^4/.test(cleanNumber)) return "Visa";
        if (/^5[1-5]/.test(cleanNumber)) return "Mastercard";
        if (/^3[47]/.test(cleanNumber)) return "Amex";
        if (/^6(?:011|5)/.test(cleanNumber)) return "Discover";

        return "Unknown";
    },

    maskCardNumber(cardNumber) {
        const cleanNumber = String(cardNumber || "").replace(/\D/g, "");

        if (cleanNumber.length <= 4) return cleanNumber;

        return "*".repeat(cleanNumber.length - 4) + cleanNumber.slice(-4);
    },

    isExpired(month, year) {
        const mm = parseInt(month, 10);
        let yy = parseInt(year, 10);

        if (Number.isNaN(mm) || Number.isNaN(yy) || mm < 1 || mm > 12) {
            return true;
        }

        // Support 2-digit year input like 26 -> 2026
        if (yy < 100) {
            yy += 2000;
        }

        const now = new Date();

        // Card expires at the END of the expiration month
        const expiryDate = new Date(yy, mm, 0, 23, 59, 59, 999);

        return expiryDate < now;
    },

    isValidCardNumber(cardNumber) {
        const cleanNumber = String(cardNumber || "").replace(/\D/g, "");

        return /^\d{15,16}$/.test(cleanNumber);
    },

    isValidCVV(cvv, cardType = "Unknown") {
        const cleanCVV = String(cvv || "").replace(/\D/g, "");

        if (cardType === "Amex") {
            return /^\d{4}$/.test(cleanCVV);
        }

        return /^\d{3}$/.test(cleanCVV);
    },

    isValidZIP(zip) {
        return /^\d{5}$/.test(String(zip || "").trim());
    },

    isValidAmount(amount) {
        const parsed = parseFloat(amount);
        return !Number.isNaN(parsed) && parsed > 0;
    },

    sanitizeFormData(formData) {
        return {
            firstName: String(formData.firstName || "").trim(),
            lastName: String(formData.lastName || "").trim(),
            address: String(formData.address || "").trim(),
            zip: String(formData.zip || "").trim(),
            cardNumber: String(formData.cardNumber || "").replace(/\D/g, ""),
            month: String(formData.month || "").trim(),
            year: String(formData.year || "").trim(),
            cvv: String(formData.cvv || "").replace(/\D/g, ""),
            amount: formData.amount
        };
    },

    validateForm(formData) {
        const errors = [];
        const data = this.sanitizeFormData(formData);
        const cardType = this.detectCardType(data.cardNumber);

        if (!data.firstName) {
            errors.push("First name is required.");
        }

        if (!data.lastName) {
            errors.push("Last name is required.");
        }

        if (!data.address) {
            errors.push("Address is required.");
        }

        if (!this.isValidCardNumber(data.cardNumber)) {
            errors.push("Card number must be 15 or 16 digits.");
        }

        const monthNum = parseInt(data.month, 10);
        if (Number.isNaN(monthNum) || monthNum < 1 || monthNum > 12) {
            errors.push("Expiration month must be between 1 and 12.");
        }

        if (!data.year || !/^\d{2,4}$/.test(data.year)) {
            errors.push("Expiration year is invalid.");
        } else if (this.isExpired(data.month, data.year)) {
            errors.push("The credit card is expired.");
        }

        if (!this.isValidCVV(data.cvv, cardType)) {
            if (cardType === "Amex") {
                errors.push("American Express CVV must be 4 digits.");
            } else {
                errors.push("CVV must be 3 digits.");
            }
        }

        if (!this.isValidZIP(data.zip)) {
            errors.push("ZIP code must be 5 digits.");
        }

        if (data.amount !== undefined && data.amount !== null && data.amount !== "") {
            if (!this.isValidAmount(data.amount)) {
                errors.push("Amount must be greater than 0.");
            }
        }

        return {
            isValid: errors.length === 0,
            errors,
            cardType,
            maskedCardNumber: this.maskCardNumber(data.cardNumber)
        };
    }
};