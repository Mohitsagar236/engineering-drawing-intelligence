import type { Metadata } from "next";
import "./style.css";
export const metadata: Metadata = {
  title: "Engineering Drawing Intelligence",
  description:
    "Traceable OCR, material reference matching, and review for engineering drawings.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
