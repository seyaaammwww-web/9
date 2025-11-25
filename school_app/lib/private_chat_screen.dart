import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // للنسخ للحافظة
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_storage/firebase_storage.dart'; // لتخزين الصور
import 'package:image_picker/image_picker.dart'; // لاختيار الصور
import 'package:animate_do/animate_do.dart';
import 'package:intl/intl.dart'; // لتنسيق الوقت

class PrivateChatScreen extends StatefulWidget {
  final String targetUserIds; 
  final String targetUserName;
  final String? targetUserImage;

  const PrivateChatScreen({
    Key? key, 
    required this.targetUserIds, 
    required this.targetUserName,
    this.targetUserImage
  }) : super(key: key);

  @override
  _PrivateChatScreenState createState() => _PrivateChatScreenState();
}

class _PrivateChatScreenState extends State<PrivateChatScreen> {
  final TextEditingController _msgController = TextEditingController();
  final String currentUserId = FirebaseAuth.instance.currentUser!.uid;
  late String chatId;
  final ScrollController _scrollController = ScrollController();
  bool _isUploading = false;

  @override
  void initState() {
    super.initState();
    List<String> ids = [currentUserId, widget.targetUserIds];
    ids.sort();
    chatId = ids.join("_");
  }

  // --- إرسال نص ---
  void _sendMessage() async {
    String msg = _msgController.text.trim();
    if (msg.isEmpty) return;
    _msgController.clear();
    await FirebaseFirestore.instance.collection('chats').doc(chatId).collection('messages').add({
      'senderId': currentUserId,
      'text': msg,
      'type': 'text', // تحديد النوع
      'timestamp': FieldValue.serverTimestamp(),
    });
  }

  // --- إرسال صورة ---
  Future<void> _sendImage() async {
    final picker = ImagePicker();
    final pickedFile = await picker.pickImage(source: ImageSource.gallery, imageQuality: 70);
    
    if (pickedFile != null) {
      setState(() => _isUploading = true);
      try {
        File file = File(pickedFile.path);
        String fileName = DateTime.now().millisecondsSinceEpoch.toString();
        Reference ref = FirebaseStorage.instance.ref().child('chat_images').child('$chatId/$fileName.jpg');
        
        await ref.putFile(file);
        String imageUrl = await ref.getDownloadURL();

        await FirebaseFirestore.instance.collection('chats').doc(chatId).collection('messages').add({
          'senderId': currentUserId,
          'text': '', // نص فارغ
          'imageUrl': imageUrl,
          'type': 'image', // نوع الرسالة صورة
          'timestamp': FieldValue.serverTimestamp(),
        });
      } catch (e) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("فشل إرسال الصورة")));
      } finally {
        setState(() => _isUploading = false);
      }
    }
  }

  // --- خيارات الرسالة (حذف/نسخ) ---
  void _showMessageOptions(DocumentSnapshot doc, bool isMe, String text) {
    showModalBottomSheet(
      context: context,
      builder: (ctx) => Container(
        padding: EdgeInsets.symmetric(vertical: 20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (text.isNotEmpty)
              ListTile(
                leading: Icon(Icons.copy, color: Color(0xFF6C63FF)),
                title: Text("نسخ النص"),
                onTap: () {
                  Clipboard.setData(ClipboardData(text: text));
                  Navigator.pop(ctx);
                  ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text("تم النسخ")));
                },
              ),
            if (isMe) // الحذف متاح للمرسل فقط
              ListTile(
                leading: Icon(Icons.delete, color: Colors.red),
                title: Text("حذف الرسالة", style: TextStyle(color: Colors.red)),
                onTap: () async {
                  Navigator.pop(ctx);
                  await doc.reference.delete();
                },
              ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            CircleAvatar(
              backgroundImage: widget.targetUserImage != null ? NetworkImage(widget.targetUserImage!) : null,
              child: widget.targetUserImage == null ? Icon(Icons.person, size: 16, color: Colors.white) : null,
              radius: 18,
              backgroundColor: Colors.grey[400],
            ),
            SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(widget.targetUserName, style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
                // يمكن ربط هذا بحالة حقيقية مستقبلاً
                Text("نشط الآن", style: TextStyle(fontSize: 10, color: Colors.greenAccent)),
              ],
            )
          ],
        ),
        backgroundColor: Color(0xFF6C63FF),
        foregroundColor: Colors.white,
        elevation: 0,
      ),
      body: Column(
        children: [
          Expanded(
            child: StreamBuilder<QuerySnapshot>(
              stream: FirebaseFirestore.instance
                  .collection('chats')
                  .doc(chatId)
                  .collection('messages')
                  .orderBy('timestamp', descending: true)
                  .snapshots(),
              builder: (context, snapshot) {
                if (!snapshot.hasData) return Center(child: CircularProgressIndicator());
                var docs = snapshot.data!.docs;

                return ListView.builder(
                  controller: _scrollController,
                  reverse: true,
                  padding: EdgeInsets.symmetric(horizontal: 15, vertical: 20),
                  itemCount: docs.length,
                  itemBuilder: (ctx, i) {
                    var doc = docs[i];
                    var data = doc.data() as Map<String, dynamic>;
                    bool isMe = data['senderId'] == currentUserId;
                    bool isImage = data['type'] == 'image';
                    
                    // تحويل الطابع الزمني للوقت
                    String time = "";
                    if (data['timestamp'] != null) {
                      Timestamp t = data['timestamp'];
                      time = DateFormat('hh:mm a', 'en').format(t.toDate());
                    }

                    return FadeInUp(
                      duration: Duration(milliseconds: 200),
                      child: Align(
                        alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
                        child: GestureDetector(
                          onLongPress: () => _showMessageOptions(doc, isMe, data['text'] ?? ""),
                          child: Container(
                            margin: EdgeInsets.only(bottom: 8),
                            padding: isImage ? EdgeInsets.all(5) : EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                            constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.75),
                            decoration: BoxDecoration(
                              gradient: isMe && !isImage ? LinearGradient(colors: [Color(0xFF6C63FF), Color(0xFF8F94FB)]) : null,
                              color: isMe ? (isImage ? Color(0xFF6C63FF) : null) : (isDark ? Color(0xFF2A2A35) : Colors.white),
                              borderRadius: BorderRadius.only(
                                topLeft: Radius.circular(20),
                                topRight: Radius.circular(20),
                                bottomLeft: isMe ? Radius.circular(20) : Radius.circular(0),
                                bottomRight: isMe ? Radius.circular(0) : Radius.circular(20),
                              ),
                              boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 5, offset: Offset(0, 2))],
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                isImage 
                                  ? ClipRRect(
                                      borderRadius: BorderRadius.circular(15),
                                      child: Image.network(data['imageUrl'], fit: BoxFit.cover, loadingBuilder: (context, child, loadingProgress) {
                                        if (loadingProgress == null) return child;
                                        return Container(height: 150, width: 200, child: Center(child: CircularProgressIndicator(color: Colors.white)));
                                      }),
                                    )
                                  : Text(
                                      data['text'],
                                      style: TextStyle(color: isMe ? Colors.white : (isDark ? Colors.white : Colors.black87), fontSize: 15, height: 1.4),
                                    ),
                                SizedBox(height: 4),
                                // الوقت
                                Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Text(time, style: TextStyle(color: isMe ? Colors.white70 : Colors.grey, fontSize: 10)),
                                    if (isMe) ...[
                                      SizedBox(width: 4),
                                      Icon(Icons.done_all, size: 12, color: Colors.white70) // علامة صح (تم الإرسال)
                                    ]
                                  ],
                                )
                              ],
                            ),
                          ),
                        ),
                      ),
                    );
                  },
                );
              },
            ),
          ),
          if (_isUploading) LinearProgressIndicator(color: Color(0xFF6C63FF), backgroundColor: Colors.grey[200]),
          Container(
            padding: EdgeInsets.all(15),
            decoration: BoxDecoration(
              color: Theme.of(context).cardColor,
              boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: Offset(0, -5))],
            ),
            child: Row(
              children: [
                // زر الصور
                IconButton(
                  icon: Icon(Icons.attach_file_rounded, color: Colors.grey),
                  onPressed: _isUploading ? null : _sendImage,
                ),
                Expanded(
                  child: TextField(
                    controller: _msgController,
                    decoration: InputDecoration(
                      hintText: "اكتب رسالة...",
                      hintStyle: TextStyle(color: Colors.grey),
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(30), borderSide: BorderSide.none),
                      filled: true,
                      fillColor: isDark ? Colors.grey[900] : Colors.grey[100],
                      contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                    ),
                  ),
                ),
                SizedBox(width: 10),
                GestureDetector(
                  onTap: _sendMessage,
                  child: Container(
                    padding: EdgeInsets.all(12),
                    decoration: BoxDecoration(color: Color(0xFF6C63FF), shape: BoxShape.circle, boxShadow: [BoxShadow(color: Color(0xFF6C63FF).withOpacity(0.4), blurRadius: 8, offset: Offset(0, 3))]),
                    child: Icon(Icons.send_rounded, color: Colors.white, size: 22),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}