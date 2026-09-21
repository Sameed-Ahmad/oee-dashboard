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

  // Distinct years (as strings) present in a sorted "YYYY-MM" months list --
  // powers the calendar's year-jump dropdown.
  function yearsFromMonths(availableMonths) {
    const years = new Set(availableMonths.map((m) => m.slice(0, 4)));
    return Array.from(years).sort();
  }

  function monthsInYear(availableMonths, year) {
    const prefix = `${year}-`;
    return availableMonths.filter((m) => m.startsWith(prefix));
  }

  // Picks the best available month in `year` given the month number the
  // user was previously looking at -- the exact same month if it has data,
  // otherwise whichever available month in that year is numerically closest.
  function closestMonthInYear(availableMonths, year, preferredMonthNum) {
    const candidates = monthsInYear(availableMonths, year);
    if (candidates.length === 0) return null;
    candidates.sort((a, b) => {
      const diffA = Math.abs(Number(a.slice(5, 7)) - preferredMonthNum);
      const diffB = Math.abs(Number(b.slice(5, 7)) - preferredMonthNum);
      return diffA - diffB;
    });
    return candidates[0];
  }

  function monthLabel(monthKey) {
    const [y, m] = monthKey.split("-").map(Number);
    return `${MONTH_NAMES[m - 1]} ${y}`;
  }

  function monthNameOnly(monthKey) {
    const m = Number(monthKey.split("-")[1]);
    return MONTH_NAMES[m - 1];
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

  return {
    monthsFromDates, monthLabel, monthNameOnly, renderMonth, oeeTier,
    yearsFromMonths, monthsInYear, closestMonthInYear,
  };
})();
