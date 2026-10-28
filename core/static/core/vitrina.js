/* Vitrina NEXUS: pestañas con avance automático, avisos en vivo, inclinación
   de los dispositivos, aparición al hacer scroll y buscador de canchas. */
(function () {
    var reducir = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.documentElement.classList.add('vt-anima');

    // ---------- Pestañas (teclado accesible + avance automático) ----------
    var tabs = Array.prototype.slice.call(document.querySelectorAll('.vt-tab'));
    var DURACION = 6500, temporizador = null, automatico = !reducir, visible = false, actual = 0;

    function activar(i, opciones) {
        opciones = opciones || {};
        actual = (i + tabs.length) % tabs.length;
        tabs.forEach(function (t, k) {
            var sel = k === actual, panel = document.getElementById(t.getAttribute('aria-controls'));
            t.setAttribute('aria-selected', sel);
            t.tabIndex = sel ? 0 : -1;
            panel.hidden = !sel;
            var barra = t.querySelector('.progreso');
            if (barra) { barra.classList.remove('corre'); }
            if (sel) {
                panel.classList.remove('entra'); void panel.offsetWidth; panel.classList.add('entra');
                if (barra && automatico && visible) { void barra.offsetWidth; barra.classList.add('corre'); }
            }
        });
        if (opciones.enfocar) tabs[actual].focus();
        programar();
    }
    function programar() {
        clearTimeout(temporizador);
        if (automatico && visible) temporizador = setTimeout(function () { activar(actual + 1); }, DURACION);
    }
    function detenerAutomatico() {
        automatico = false; clearTimeout(temporizador);
        tabs.forEach(function (t) { var b = t.querySelector('.progreso'); if (b) b.classList.remove('corre'); });
    }
    tabs.forEach(function (t, i) {
        var b = t.querySelector('.progreso'); if (b) b.style.setProperty('--dur', DURACION + 'ms');
        t.addEventListener('click', function () { detenerAutomatico(); activar(i); });
        t.addEventListener('keydown', function (e) {
            var n = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
            if (n === undefined) return;
            e.preventDefault(); detenerAutomatico(); activar(n, { enfocar: true });
        });
    });
    var recorrido = document.getElementById('recorrido');
    if (recorrido && tabs.length && 'IntersectionObserver' in window) {
        new IntersectionObserver(function (en) {
            visible = en[0].isIntersecting;
            if (visible) activar(actual); else { clearTimeout(temporizador); }
        }, { threshold: .35 }).observe(recorrido);
        // Si la persona pasa el mouse por el contenido, se espera a que termine de mirar
        recorrido.addEventListener('pointerenter', function (e) { if (e.pointerType === 'mouse') clearTimeout(temporizador); });
        recorrido.addEventListener('pointerleave', function (e) { if (e.pointerType === 'mouse') programar(); });
    }

    // ---------- Avisos "en vivo" sobre los dispositivos ----------
    var avisos = Array.prototype.slice.call(document.querySelectorAll('.vt-aviso'));
    if (avisos.length) {
        if (reducir) { avisos[0].classList.add('ver'); }
        else {
            var paso = 0;
            var mostrar = function () {
                avisos.forEach(function (a, k) { a.classList.toggle('ver', k === paso % avisos.length || k === (paso + 1) % avisos.length); });
                paso++;
            };
            setTimeout(function () { mostrar(); setInterval(mostrar, 3200); }, 1300);
        }
    }

    // ---------- Inclinación suave de la escena con el mouse ----------
    var escena = document.querySelector('.vt-escena');
    if (escena && !reducir && window.matchMedia('(hover: hover) and (pointer: fine)').matches) {
        var combo = escena.querySelector('.combo'), marco = null;
        escena.addEventListener('pointermove', function (e) {
            var r = escena.getBoundingClientRect();
            var x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
            cancelAnimationFrame(marco);
            marco = requestAnimationFrame(function () { combo.style.transform = 'rotateY(' + (x * 7) + 'deg) rotateX(' + (-y * 5) + 'deg)'; });
        });
        escena.addEventListener('pointerleave', function () { cancelAnimationFrame(marco); combo.style.transform = ''; });
    }

    // ---------- Aparición al hacer scroll (con cascada) ----------
    var els = document.querySelectorAll('.revela');
    if (!('IntersectionObserver' in window)) { els.forEach(function (el) { el.classList.add('visto'); }); }
    else {
        var io = new IntersectionObserver(function (entradas) {
            entradas.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add('visto'); io.unobserve(en.target); } });
        }, { rootMargin: '0px 0px -8% 0px' });
        els.forEach(function (el) { io.observe(el); });
    }

    // ---------- Buscador de canchas ----------
    var buscador = document.getElementById('buscadorCanchas');
    if (buscador) {
        var tarjetas = document.querySelectorAll('.vt-cancha-item'), vacio = document.getElementById('sinResultados');
        buscador.addEventListener('input', function () {
            var q = buscador.value.toLowerCase().trim(), hay = false;
            tarjetas.forEach(function (c) { var ok = c.getAttribute('data-nombre').indexOf(q) !== -1; c.hidden = !ok; hay = hay || ok; });
            if (vacio) vacio.hidden = hay || !q;
        });
    }
})();
