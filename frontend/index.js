import './style.scss';
import 'bootstrap';
import tippy from 'tippy.js';

class App {

    static copyToClipboard(button) {
        let text = button.parentNode.getElementsByTagName("code")[0].innerText
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text);
            let oldInner = button.innerHTML;
            button.innerHTML = "✅";
            setTimeout(() => button.innerHTML = oldInner, 1000);
        }
    }

};

tippy('.mytooltip', {
    allowHTML: true,
    theme: 'light-border',
    content(reference) {
        return reference.querySelector(".mytooltip-content").innerHTML;
    },
});

window.App = App;
