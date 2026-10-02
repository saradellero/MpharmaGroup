(function () {
  "use strict";

  function validParts(day, month, year) {
    var candidate = new Date(Date.UTC(year, month - 1, day));
    return candidate.getUTCFullYear() === year &&
      candidate.getUTCMonth() === month - 1 &&
      candidate.getUTCDate() === day;
  }

  function parseDate(value) {
    var text = String(value || "").trim();
    var match = text.match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (match) {
      var day = Number(match[1]);
      var month = Number(match[2]);
      var year = Number(match[3]);
      if (validParts(day, month, year)) {
        return {
          day: day,
          month: month,
          year: year,
          iso: match[3] + "-" + match[2] + "-" + match[1]
        };
      }
      return null;
    }

    match = text.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) {
      return null;
    }
    var isoYear = Number(match[1]);
    var isoMonth = Number(match[2]);
    var isoDay = Number(match[3]);
    if (!validParts(isoDay, isoMonth, isoYear)) {
      return null;
    }
    return {
      day: isoDay,
      month: isoMonth,
      year: isoYear,
      iso: text
    };
  }

  function displayValue(parts) {
    return String(parts.day).padStart(2, "0") + "/" +
      String(parts.month).padStart(2, "0") + "/" +
      String(parts.year).padStart(4, "0");
  }

  function validationMessage() {
    return document.documentElement.lang === "fr"
      ? "Saisissez une date valide au format jj/mm/aaaa."
      : "Introduce una fecha valida con el formato dd/mm/aaaa.";
  }

  function initializeDateControl(control) {
    var display = control.querySelector("[data-date-display]");
    var picker = control.querySelector("[data-date-picker]");
    var openButton = control.querySelector("[data-date-open]");
    if (!display) {
      return;
    }

    function synchronize(showError) {
      var rawValue = display.value.trim();
      if (!rawValue) {
        display.setCustomValidity("");
        if (picker) {
          picker.value = "";
        }
        return true;
      }

      var parsed = parseDate(rawValue);
      if (!parsed) {
        display.setCustomValidity(showError ? validationMessage() : "");
        return false;
      }

      display.value = displayValue(parsed);
      display.setCustomValidity("");
      if (picker) {
        picker.value = parsed.iso;
      }
      return true;
    }

    synchronize(false);
    display.addEventListener("input", function () {
      display.setCustomValidity("");
    });
    display.addEventListener("blur", function () {
      synchronize(true);
    });
    display.addEventListener("invalid", function () {
      synchronize(true);
    });

    if (picker) {
      picker.addEventListener("change", function () {
        var parsed = parseDate(picker.value);
        if (parsed) {
          display.value = displayValue(parsed);
          display.setCustomValidity("");
        }
      });
    }

    if (openButton && picker) {
      openButton.addEventListener("click", function () {
        synchronize(false);
        if (typeof picker.showPicker === "function") {
          picker.showPicker();
        } else {
          picker.focus();
          picker.click();
        }
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-date-control]").forEach(initializeDateControl);
  });
})();
