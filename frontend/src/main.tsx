import React from "react";
import ReactDOM from "react-dom/client";
import { HeroUIProvider } from "@heroui/react";
import App from "./App";
import { locale, t } from "./i18n";
import "./styles.css";
document.documentElement.lang = locale;
document
  .querySelector('meta[name="description"]')
  ?.setAttribute("content", t("Pan 文件存储与分享。"));
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HeroUIProvider locale={locale}>
      <App />
    </HeroUIProvider>
  </React.StrictMode>,
);
