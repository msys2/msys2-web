(() => {
    'use strict'

function setupDarkMode() {
    const storedTheme = localStorage.getItem('theme')

    const getPreferredTheme = () => {
        if (storedTheme) {
            return storedTheme
        }
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    }
    
    const setTheme = function (theme) {
        if (theme === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            document.documentElement.setAttribute('data-bs-theme', 'dark')
        } else {
            document.documentElement.setAttribute('data-bs-theme', theme)
        }
    }
    
    setTheme(getPreferredTheme())
    
    const showActiveTheme = theme => {
        document.querySelector(`#dark-mode-check`).checked = (theme == "dark");
        document.querySelector('#dark-mode-label').innerText = (theme == "light") ? "☀️" : "🌒";
    }
    
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        if (storedTheme !== 'light' || storedTheme !== 'dark') {
            setTheme(getPreferredTheme())
        }
    })
    
    window.addEventListener('DOMContentLoaded', () => {
        showActiveTheme(getPreferredTheme())
    
        const checkbox = document.querySelector('#dark-mode-check');
        checkbox.addEventListener('click', () => {
            const theme = checkbox.checked ? 'dark' : 'light';
            localStorage.setItem('theme', theme)
            setTheme(theme)
            showActiveTheme(theme)
        });
    })
}

setupDarkMode();
})()