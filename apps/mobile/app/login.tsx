import { useState } from "react";
import { router } from "expo-router";
import { Alert, Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { Screen } from "@/components/Screen";
import { login } from "@/lib/api";
export default function Login(){const[email,setEmail]=useState("buyer@nestora.local");const[password,setPassword]=useState("");const[loading,setLoading]=useState(false);async function submit(){setLoading(true);try{await login(email,password);router.replace("/(tabs)")}catch(e){Alert.alert("Không thể đăng nhập",String(e))}finally{setLoading(false)}}return <Screen title="Đăng nhập"><View style={s.card}><TextInput autoCapitalize="none" keyboardType="email-address" placeholder="Email" value={email} onChangeText={setEmail} style={s.input}/><TextInput secureTextEntry placeholder="Mật khẩu" value={password} onChangeText={setPassword} style={s.input}/><Pressable disabled={loading} onPress={()=>void submit()} style={s.button}><Text style={s.buttonText}>{loading?"Đang đăng nhập…":"Đăng nhập"}</Text></Pressable></View></Screen>}
const s=StyleSheet.create({card:{padding:18,borderRadius:18,backgroundColor:"white",gap:12},input:{borderWidth:1,borderColor:"#ddd5c6",borderRadius:12,padding:14},button:{padding:15,borderRadius:12,backgroundColor:"#1d5f4a"},buttonText:{color:"white",fontWeight:"700",textAlign:"center"}});
