import './style.scss';
import 'bootstrap';

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

window.App = App;
