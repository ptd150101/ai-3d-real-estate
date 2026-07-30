"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { clientApi } from "@/lib/client-api";
export function DirectMessageButton({propertyId,agentId}:{propertyId?:string;agentId?:string}){const router=useRouter();const[busy,setBusy]=useState(false);return <button className="btn btn-primary" disabled={busy} onClick={async()=>{setBusy(true);try{const thread=await clientApi<any>("/messages/threads",{method:"POST",body:JSON.stringify({property_id:propertyId,agent_id:agentId,subject:"Tư vấn bất động sản"})});router.push(`/messages?thread=${thread.id}`)}catch{router.push("/login")}finally{setBusy(false)}}}>{busy?"Đang mở…":"Nhắn môi giới"}</button>}
