"use client";
import { useState } from "react";
import { AppointmentForm } from "./AppointmentForm";
import { FavoriteButton } from "./FavoriteButton";
import { CompareButton } from "./CompareButton";
export function SummaryActions({propertyId,phone}:{propertyId:string;phone?:string|null}){const[open,setOpen]=useState(false);return <><div className="stack"><button className="btn btn-primary" onClick={()=>setOpen(true)}>Đặt lịch xem nhà</button>{phone&&<a className="btn btn-secondary" href={`tel:${phone}`}>Gọi môi giới: {phone}</a>}<div className="grid grid-2"><FavoriteButton propertyId={propertyId}/><CompareButton propertyId={propertyId}/></div></div><AppointmentForm propertyId={propertyId} open={open} onClose={()=>setOpen(false)}/></>}
