// The ONE place the site's logo is set. Header, footer, favicon and app icon all use this file,
// and the PDF report reads the same file (frontend/public/logo.png, mounted into the report
// containers by docker-compose.yml). To change the logo, replace frontend/public/logo.png.
export const BRAND_NAME = "Turnitin Reports";
export const LOGO_URL = "/logo.png?v=2";
