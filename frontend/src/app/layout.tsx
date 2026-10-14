import type { Metadata } from "next";
import "./globals.css";
import { ApplicationProviders } from "@/components/layout/application-providers";
export const metadata: Metadata = { title: "共立 RAG", description: "Document-grounded conversations" };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="ja" className="h-full antialiased"><body className="min-h-full flex flex-col"><ApplicationProviders>{children}</ApplicationProviders></body></html>;
}
