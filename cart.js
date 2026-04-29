function getCartItems() {
  const cart = localStorage.getItem("cart");
  const parsed = cart ? JSON.parse(cart) : [];

  return parsed.map(item => ({
    name: item.name,
    price: Number(item.price),
    quantity: Number(item.quantity ?? item.qty ?? 1)
  }));
}

function updateCartCount() {
  const cartItems = getCartItems();
  const totalCount = cartItems.reduce((sum, item) => sum + item.quantity, 0);

  document.querySelectorAll(".cart-count").forEach(el => {
    el.textContent = totalCount;
  });
}

function renderCartPage() {
  const cartItems = getCartItems();
  const cartItemsContainer = document.getElementById("cart-items");
  const cartSubtotal = document.getElementById("subtotal") || document.getElementById("cart-subtotal");
  const cartTax = document.getElementById("tax") || document.getElementById("cart-tax");
  const cartTotal = document.getElementById("total") || document.getElementById("cart-total");

  if (!cartItemsContainer) return;

  if (cartItems.length === 0) {
    cartItemsContainer.innerHTML = "<p>Your cart is empty.</p>";
    if (cartSubtotal) cartSubtotal.textContent = "$0.00";
    if (cartTax) cartTax.textContent = "$0.00";
    if (cartTotal) cartTotal.textContent = "$0.00";
    return;
  }

  let subtotal = 0;

  cartItemsContainer.innerHTML = cartItems.map(item => {
    const lineTotal = item.price * item.quantity;
    subtotal += lineTotal;

    return `
      <div class="cart-item" style="display:flex; justify-content:space-between; align-items:center; padding:1rem 0; border-bottom:1px solid #eee;">
        <div>
          <h3 style="margin:0 0 .25rem 0;">${item.name}</h3>
          <p style="margin:0; color:#666;">Quantity: ${item.quantity}</p>
          <p style="margin:.25rem 0 0 0; color:#666;">$${item.price.toFixed(2)} each</p>
        </div>
        <div style="font-weight:600;">$${lineTotal.toFixed(2)}</div>
      </div>
    `;
  }).join("");

  const tax = subtotal * 0.08;
  const total = subtotal + tax;

  if (cartSubtotal) cartSubtotal.textContent = "$" + subtotal.toFixed(2);
  if (cartTax) cartTax.textContent = "$" + tax.toFixed(2);
  if (cartTotal) cartTotal.textContent = "$" + total.toFixed(2);
}

document.addEventListener("DOMContentLoaded", () => {
  updateCartCount();
  renderCartPage();
});