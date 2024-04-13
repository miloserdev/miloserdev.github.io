document.addEventListener("DOMContentLoaded", () =>
{
    console.log("darklight enabled");

    let icon = document.querySelectorAll("img[icon]")[0];

    let darklight = () => document.body.getAttribute("theme") == "dark" ? "light" : "dark";

    icon.addEventListener("click", () => { console.log(darklight()); document.body.setAttribute("theme", darklight()) });
    
});
