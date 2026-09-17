;(function () {
  // ---- Billing toggle -----------------------------------------------------
  var billingButtons = document.querySelectorAll('[data-billing]')

  function currentBilling() {
    var active = document.querySelector('[data-billing][aria-pressed="true"]')
    return active ? active.getAttribute('data-billing') : 'annual'
  }

  function setBilling(mode) {
    billingButtons.forEach(function (button) {
      var active = button.getAttribute('data-billing') === mode
      button.setAttribute('aria-pressed', active ? 'true' : 'false')
      button.classList.toggle('text-ink', active)
      button.classList.toggle('text-ink-muted', !active)
    })

    document.querySelectorAll('[data-price]').forEach(function (el) {
      el.textContent = el.getAttribute('data-' + mode) || el.textContent
    })

    document.querySelectorAll('[data-cadence]').forEach(function (el) {
      el.textContent = el.getAttribute('data-' + mode) || el.textContent
    })

    document.querySelectorAll('[data-annual-only]').forEach(function (el) {
      el.hidden = mode !== 'annual'
    })

    var underline = document.querySelector('[data-toggle-underline]')
    if (underline) {
      var active = document.querySelector('[data-billing="' + mode + '"]')
      if (active) {
        underline.style.transform = 'translateX(' + active.offsetLeft + 'px)'
        underline.style.width = active.offsetWidth + 'px'
      }
    }
  }

  if (billingButtons.length) {
    billingButtons.forEach(function (button) {
      button.addEventListener('click', function () {
        setBilling(button.getAttribute('data-billing'))
      })
    })
    setBilling(currentBilling())
    window.addEventListener('resize', function () {
      setBilling(currentBilling())
    })
  }

  // ---- Mobile representation of comparison tables -------------------------
  document.querySelectorAll('table[data-compare]').forEach(function (table) {
    var headers = Array.prototype.map.call(table.querySelectorAll('thead th'), function (th) {
      return th.textContent.trim()
    })

    var wrap = document.createElement('div')
    wrap.className = 'md:hidden'

    table.querySelectorAll('tbody tr').forEach(function (tr) {
      var cells = tr.querySelectorAll('td')
      if (!cells.length) return

      var row = document.createElement('div')
      row.className = 'border-t border-line py-3'

      var name = document.createElement('div')
      name.className = 'text-[15px]'
      name.textContent = cells[0].textContent.trim()
      row.appendChild(name)

      var values = document.createElement('div')
      values.className = 'mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-ink-secondary'
      for (var i = 1; i < cells.length; i++) {
        var span = document.createElement('span')
        span.innerHTML =
          '<span class="text-ink-muted">' + (headers[i] || '') + '</span> ' + cells[i].textContent.trim()
        values.appendChild(span)
      }
      row.appendChild(values)
      wrap.appendChild(row)
    })

    table.parentNode.insertBefore(wrap, table.nextSibling)
  })
})()
