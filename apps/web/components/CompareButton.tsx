"use client";
import { useEffect, useState } from "react";
const KEY="nestora_compare";
export function CompareButton({propertyId}:{propertyId:string}){
  const [added,setAdded]=useState(false);
  useEffect(()=>{try{setAdded((JSON.parse(localStorage.getItem(KEY)||"[]") as string[]).includes(propertyId));}catch{}},[propertyId]);
  function toggle(){const current=new Set<string>(JSON.parse(localStorage.getItem(KEY)||"[]")); if(current.has(propertyId))current.delete(propertyId);else{if(current.size>=4){alert("Chỉ so sánh tối đa 4 căn");return;}current.add(propertyId);} localStorage.setItem(KEY,JSON.stringify([...current]));setAdded(current.has(propertyId));}
  return <button className="btn btn-secondary" type="button" onClick={toggle}>{added?"✓ Đã thêm so sánh":"⇄ So sánh"}</button>;
}
