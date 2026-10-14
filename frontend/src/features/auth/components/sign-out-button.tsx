"use client";
import { LogOutIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

export function SignOutButton() {
  return <Button variant="ghost" className="w-full justify-start gap-2" onClick={() => {sessionStorage.removeItem("rag-access-token"); location.reload();}}><LogOutIcon className="size-4" />Sign out</Button>;
}
