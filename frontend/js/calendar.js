// Month-calendar popup logic: which months have data, and rendering a single
// month's grid with OEE-tier color dots.
const Calendar = (() => {
  const DOW_LABELS = ["S", "M", "T", "W", "T", "F", "S"];
  const MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];

  function monthsFromDates(isoDates) {
    const months = new Set();
    for (const d of isoDates) {
      months.add(d.slice(0, 7)); // "YYYY-MM"
    }
    return Array.from(months).sort();
  }

  function monthLabel(monthKey) {
    const [y, m] = monthKey.split("-").map(Number);
    return `${MONTH_NAMES[m - 1]} ${y}`;
  }

  function oeeTier(oeePct) {
    if (oeePct >= 90) return "good";
    if (oeePct >= 80) return "ok";
    return "bad";
  }

  // Renders the calendar grid for `monthKey` ("YYYY-MM") into `gridEl`.
  // recordsByDate: { "YYYY-MM-DD": DayRecord }
  function renderMonth(gridEl, monthKey, recordsByDate, selectedDate, onSelectDay) {
    gridEl.innerHTML = "";

    for (const label of DOW_LABELS) {
      const el = document.createElement("div");
      el.className = "calendar-dow";
      el.textContent = label;
      gridEl.appendChild(el);
    }

    const [year, month] = monthKey.split("-").map(Number);
    const firstOfMonth = new Date(year, month - 1, 1);
    const daysInMonth = new Date(year, month, 0).getDate();
    const startWeekday = firstOfMonth.getDay();

    for (let i = 0; i < startWeekday; i++) {
      const el = document.createElement("div");
      el.className = "calendar-day empty";
      gridEl.appendChild(el);
    }

    for (let day = 1; day <= daysInMonth; day++) {
      const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      const record = recordsByDate[dateStr];
      const cell = document.createElement("div");
      cell.textContent = String(day);

      if (record) {
        cell.className = "calendar-day" + (dateStr === selectedDate ? " selected" : "");
        const dot = document.createElement("span");
        dot.className = `dot dot-${oeeTier(record.oeePct)}`;
        cell.appendChild(dot);
        if (record.shiftCount > 1) {
          const badge = document.createElement("span");
          badge.className = "shift-badge";
          badge.textContent = record.shiftCount;
          badge.title = `${record.shiftCount} shifts reported`;
          cell.appendChild(badge);
        }
        cell.addEventListener("click", () => onSelectDay(dateStr));
        cell.title = `${dateStr} — OEE ${record.oeePct}%`;
      } else {
        cell.className = "calendar-day inert";
      }

      gridEl.appendChild(cell);
    }
  }

  return { monthsFromDates, monthLabel, renderMonth, oeeTier };
})();
