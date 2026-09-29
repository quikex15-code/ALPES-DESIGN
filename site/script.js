(function () {
  'use strict';

  var CONTACT_EMAIL = 'contact@alpes-design.com';
  var DURATION = 300; // ms — no transition longer than 0.3s
  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Our own scroll handles timing, so disable the CSS one to avoid double easing.
  document.documentElement.style.scrollBehavior = 'auto';

  /* ---------- Intro ---------- */
  var intro = document.getElementById('intro');
  if (intro && document.documentElement.classList.contains('has-intro')) {
    var root = document.documentElement;
    function endIntro() { root.classList.add('intro-done'); }
    intro.addEventListener('animationend', function (e) {
      if (e.target === intro) endIntro();
    });
    // A click or a key skips the intro.
    intro.addEventListener('click', endIntro);
    document.addEventListener('keydown', function onKey() {
      endIntro();
      document.removeEventListener('keydown', onKey);
    });
  }

  /* ---------- Smooth scroll (0.3s) ---------- */
  function headerOffset() {
    var header = document.querySelector('.site-header');
    return header ? header.offsetHeight : 0;
  }

  function scrollToY(targetY) {
    if (reduceMotion) { window.scrollTo(0, targetY); return; }
    var startY = window.pageYOffset;
    var delta = targetY - startY;
    var start = null;
    function ease(t) { return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t; }
    function step(ts) {
      if (start === null) start = ts;
      var p = Math.min((ts - start) / DURATION, 1);
      window.scrollTo(0, startY + delta * ease(p));
      if (p < 1) window.requestAnimationFrame(step);
    }
    window.requestAnimationFrame(step);
  }

  document.addEventListener('click', function (e) {
    var link = e.target.closest('a[href^="#"]');
    if (!link) return;
    var id = link.getAttribute('href');
    if (id.length < 2) return;
    var target = document.querySelector(id);
    if (!target) return;
    e.preventDefault();
    var y = id === '#top' ? 0 : target.getBoundingClientRect().top + window.pageYOffset - headerOffset();
    scrollToY(Math.max(0, y));
    if (history.pushState) history.pushState(null, '', id);
    closeNav();
  });

  /* ---------- Mobile nav ---------- */
  var navToggle = document.querySelector('.nav-toggle');
  var nav = document.getElementById('site-nav');

  function closeNav() {
    if (!nav || !navToggle) return;
    nav.classList.remove('is-open');
    navToggle.setAttribute('aria-expanded', 'false');
    navToggle.textContent = 'Menu';
  }

  if (navToggle && nav) {
    navToggle.addEventListener('click', function () {
      var open = nav.classList.toggle('is-open');
      navToggle.setAttribute('aria-expanded', String(open));
      navToggle.textContent = open ? 'Fermer' : 'Menu';
    });
  }

  /* ---------- Back to top ---------- */
  var toTop = document.getElementById('to-top');
  var ticking = false;
  function updateToTop() {
    toTop.classList.toggle('is-visible', window.pageYOffset > 600);
    ticking = false;
  }
  if (toTop) {
    window.addEventListener('scroll', function () {
      if (!ticking) { window.requestAnimationFrame(updateToTop); ticking = true; }
    }, { passive: true });
    updateToTop();
  }

  /* ---------- FAQ accordion ---------- */
  document.querySelectorAll('.faq-q button').forEach(function (btn) {
    var panel = document.getElementById(btn.getAttribute('aria-controls'));
    var icon = btn.querySelector('.faq-icon');

    btn.addEventListener('click', function () {
      var open = btn.getAttribute('aria-expanded') === 'true';
      btn.setAttribute('aria-expanded', String(!open));
      icon.textContent = open ? '+' : '−';

      if (reduceMotion) { panel.hidden = open; return; }

      if (open) {
        panel.style.height = panel.scrollHeight + 'px';
        panel.offsetHeight; // force reflow
        panel.style.height = '0px';
        onTransitionEnd(panel, function () { panel.hidden = true; panel.style.height = ''; });
      } else {
        panel.hidden = false;
        panel.style.height = '0px';
        panel.offsetHeight;
        panel.style.height = panel.scrollHeight + 'px';
        onTransitionEnd(panel, function () { panel.style.height = ''; });
      }
    });
  });

  function onTransitionEnd(el, fn) {
    var done = false;
    function finish() { if (done) return; done = true; el.removeEventListener('transitionend', finish); fn(); }
    el.addEventListener('transitionend', finish);
    setTimeout(finish, DURATION + 50);
  }

  /* ---------- Portfolio plans (lightbox) ---------- */
  var lightbox = document.getElementById('lightbox');

  document.querySelectorAll('.plan img').forEach(function (img) {
    // Drop the frame if the plan file isn't there yet, instead of a broken image.
    function hide() { img.closest('.plan').remove(); }
    if (img.complete && img.naturalWidth === 0) hide();
    else img.addEventListener('error', hide);
  });

  if (lightbox && typeof lightbox.showModal === 'function') {
    var lbImg = lightbox.querySelector('.lightbox-img');
    var lbCaption = lightbox.querySelector('.lightbox-caption');

    document.querySelectorAll('.plan-open').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var img = btn.querySelector('img');
        lbImg.src = img.currentSrc || img.src;
        lbImg.alt = img.alt;
        lbCaption.textContent = img.alt;
        lightbox.showModal();
      });
    });

    lightbox.querySelector('.lightbox-close').addEventListener('click', function () { lightbox.close(); });
    // Click outside the image closes too.
    lightbox.addEventListener('click', function (e) { if (e.target === lightbox) lightbox.close(); });
  } else {
    // Very old browsers: open the plan file directly.
    document.querySelectorAll('.plan-open').forEach(function (btn) {
      btn.addEventListener('click', function () { window.open(btn.querySelector('img').src, '_blank'); });
    });
  }

  /* ---------- Contact form ---------- */
  var form = document.getElementById('contact-form');
  if (!form) return;

  var status = document.getElementById('form-status');
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  function setError(input, message) {
    var err = document.getElementById(input.id + '-error');
    if (message) {
      input.setAttribute('aria-invalid', 'true');
      input.setAttribute('aria-describedby', input.id + '-error');
    } else {
      input.removeAttribute('aria-invalid');
      input.removeAttribute('aria-describedby');
    }
    if (err) err.textContent = message || '';
  }

  function validateField(input) {
    var value = input.value.trim();
    if (input.required && !value) {
      setError(input, 'Ce champ est requis.');
      return false;
    }
    if (input.type === 'email' && value && !EMAIL_RE.test(value)) {
      setError(input, 'Veuillez saisir une adresse email valide.');
      return false;
    }
    setError(input, '');
    return true;
  }

  var requiredFields = form.querySelectorAll('[required]');
  requiredFields.forEach(function (input) {
    input.addEventListener('blur', function () { validateField(input); });
    input.addEventListener('input', function () {
      if (input.getAttribute('aria-invalid') === 'true') validateField(input);
    });
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var firstInvalid = null;
    requiredFields.forEach(function (input) {
      if (!validateField(input) && !firstInvalid) firstInvalid = input;
    });
    if (firstInvalid) {
      status.textContent = '';
      firstInvalid.focus();
      return;
    }

    var data = {
      company: form.company.value.trim(),
      email: form.email.value.trim(),
      description: form.description.value.trim(),
      budget: form.budget.value.trim()
    };

    // No backend: hand the request to the visitor's mail client, pre-filled.
    var subject = 'Demande de projet — ' + data.company;
    var body = [
      'Compagnie : ' + data.company,
      'Email : ' + data.email,
      'Budget estimé : ' + (data.budget || 'non précisé'),
      '',
      'Description du projet :',
      data.description || '—'
    ].join('\n');

    window.location.href = 'mailto:' + CONTACT_EMAIL +
      '?subject=' + encodeURIComponent(subject) +
      '&body=' + encodeURIComponent(body);

    status.textContent = 'Merci. Votre messagerie s\'ouvre avec la demande pré-remplie — il ne reste qu\'à l\'envoyer.';
    form.reset();
  });
})();
