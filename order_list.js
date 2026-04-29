document.addEventListener("DOMContentLoaded", () => {
  const statusFilter = document.getElementById("status-filter");
  const tableBody = document.querySelector("#order-table tbody");

  if (!tableBody) return;

  const getRows = () => Array.from(tableBody.querySelectorAll("tr"));

  if (statusFilter) {
    statusFilter.addEventListener("change", (e) => {
      const selectedStatus = e.target.value.toLowerCase();

      getRows().forEach((row) => {
        const statusCell = row.querySelector(".status-cell");
        if (!statusCell) return;

        const statusText = statusCell.innerText.trim().toLowerCase();

        if (selectedStatus === "all" || statusText === selectedStatus) {
          row.style.display = "";
        } else {
          row.style.display = "none";
        }
      });
    });
  }
});

function sortOrders(criteria) {
  const tableBody = document.querySelector("#order-table tbody");
  if (!tableBody) return;

  const rows = Array.from(tableBody.querySelectorAll("tr")).filter(row =>
    row.querySelector(".amount-cell") || row.querySelector(".date-cell")
  );

  rows.sort((a, b) => {
    if (criteria === "amount") {
      const aAmount = parseFloat(
        a.querySelector(".amount-cell")?.innerText.replace(/[^0-9.-]+/g, "") || "0"
      );
      const bAmount = parseFloat(
        b.querySelector(".amount-cell")?.innerText.replace(/[^0-9.-]+/g, "") || "0"
      );
      return bAmount - aAmount;
    }

    if (criteria === "date") {
      const aDateText = a.querySelector(".date-cell")?.innerText.trim() || "";
      const bDateText = b.querySelector(".date-cell")?.innerText.trim() || "";
      const aDate = new Date(aDateText);
      const bDate = new Date(bDateText);
      return bDate - aDate;
    }

    return 0;
  });

  rows.forEach((row) => tableBody.appendChild(row));
}