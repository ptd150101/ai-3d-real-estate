import { useState } from "react";
import * as ImagePicker from "expo-image-picker";
import * as FileSystem from "expo-file-system/legacy";
import { Alert, Image, Pressable, StyleSheet, Text } from "react-native";
import { Screen } from "@/components/Screen";
import { enqueue } from "@/lib/offline";
export default function Capture(){const[uri,setUri]=useState<string|null>(null);async function choose(){const permission=await ImagePicker.requestCameraPermissionsAsync();if(!permission.granted)return Alert.alert("Cần quyền camera");const result=await ImagePicker.launchCameraAsync({quality:.8,exif:false});if(result.canceled)return;const asset=result.assets[0];const info=await FileSystem.getInfoAsync(asset.uri,{md5:true});if(!info.exists||!info.size||info.size>25*1024*1024)return Alert.alert("Tệp không hợp lệ","Ảnh tối đa 25 MB.");setUri(asset.uri);await enqueue("capture.metadata",{uri:asset.uri,size_bytes:info.size,md5:info.md5,mime_type:asset.mimeType??"image/jpeg"})}return <Screen title="Capture 3D"><Text>Chụp theo vòng quanh phòng, giữ độ sáng ổn định và chồng lấn ít nhất 60% giữa hai ảnh.</Text><Pressable style={s.button} onPress={()=>void choose()}><Text style={s.buttonText}>Chụp ảnh kiểm tra</Text></Pressable>{uri&&<Image source={{uri}} style={s.image}/>}</Screen>}
const s=StyleSheet.create({button:{backgroundColor:"#1d5f4a",padding:15,borderRadius:12},buttonText:{color:"white",fontWeight:"700",textAlign:"center"},image:{height:320,borderRadius:18}});
