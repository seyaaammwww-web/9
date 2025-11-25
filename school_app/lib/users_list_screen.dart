import 'package:flutter/material.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:animate_do/animate_do.dart';
import 'private_chat_screen.dart';

class UsersListScreen extends StatefulWidget {
  @override
  _UsersListScreenState createState() => _UsersListScreenState();
}

class _UsersListScreenState extends State<UsersListScreen> {
  final TextEditingController _searchController = TextEditingController();
  String _searchText = "";
  final String myId = FirebaseAuth.instance.currentUser?.uid ?? "";

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  // دالة مساعدة لتحديد "اللقب" بناءً على النقاط
  String _getUserTitle(int points) {
    if (points > 1000) return "خبير 🎓";
    if (points > 500) return "متقدم 🚀";
    if (points > 200) return "نشيط 🔥";
    return "عضو جديد 🌱";
  }

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    final cardColor = Theme.of(context).cardColor;

    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
      appBar: AppBar(
        title: Text("مجتمع يُــــسر"),
        centerTitle: true,
        elevation: 0,
        bottom: PreferredSize(
          preferredSize: Size.fromHeight(60),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 0, 20, 15),
            child: TextField(
              controller: _searchController,
              onChanged: (val) => setState(() => _searchText = val),
              decoration: InputDecoration(
                hintText: "ابحث عن طالب أو معلم...",
                prefixIcon: Icon(Icons.search, color: Colors.grey),
                suffixIcon: _searchText.isNotEmpty 
                  ? IconButton(icon: Icon(Icons.clear, size: 18), onPressed: () => setState(() { _searchController.clear(); _searchText = ""; })) 
                  : null,
                filled: true,
                fillColor: isDark ? Colors.white10 : Colors.grey[200],
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(30), borderSide: BorderSide.none),
                contentPadding: EdgeInsets.symmetric(horizontal: 20, vertical: 0),
              ),
            ),
          ),
        ),
      ),
      body: StreamBuilder<QuerySnapshot>(
        // جلب المستخدمين (يمكن تحسينه باستخدام limit للبيانات الكبيرة)
        stream: FirebaseFirestore.instance.collection('users').where(FieldPath.documentId, isNotEqualTo: myId).snapshots(),
        builder: (context, snapshot) {
          if (!snapshot.hasData) return Center(child: CircularProgressIndicator());
          
          // فلترة القائمة محلياً للبحث (لأن فايرستور لا يدعم البحث النصي الجزئي بسهولة)
          var docs = snapshot.data!.docs.where((doc) {
            var data = doc.data() as Map<String, dynamic>;
            String name = (data['name'] ?? "").toLowerCase();
            return name.contains(_searchText.toLowerCase());
          }).toList();

          if (docs.isEmpty) {
            return Center(child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              Icon(Icons.person_search_rounded, size: 80, color: Colors.grey[300]),
              SizedBox(height: 10),
              Text(_searchText.isEmpty ? "لا يوجد أعضاء آخرين" : "لم يتم العثور على نتائج", style: TextStyle(color: Colors.grey)),
            ]));
          }

          return ListView.builder(
            padding: EdgeInsets.symmetric(horizontal: 20, vertical: 10),
            itemCount: docs.length,
            itemBuilder: (ctx, i) {
              var user = docs[i];
              var data = user.data() as Map<String, dynamic>;
              
              String? photoUrl = data['photoUrl'];
              String role = data['role'] ?? 'student';
              String name = data['name'] ?? 'مستخدم';
              int points = data['totalPoints'] ?? 0;
              
              // محاكاة لحالة الاتصال (يمكن ربطها بحقل حقيقي لاحقاً)
              bool isOnline = i % 3 == 0; // مثال: كل ثالث مستخدم "متصل"

              return FadeInUp(
                duration: Duration(milliseconds: 300),
                child: Container(
                  margin: EdgeInsets.only(bottom: 15),
                  decoration: BoxDecoration(
                    color: cardColor,
                    borderRadius: BorderRadius.circular(18),
                    boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.05), blurRadius: 10, offset: Offset(0, 4))],
                    border: role == 'teacher' ? Border.all(color: Colors.orange.withOpacity(0.3), width: 1) : null,
                  ),
                  child: ListTile(
                    contentPadding: EdgeInsets.symmetric(horizontal: 15, vertical: 8),
                    // الصورة + مؤشر الحالة
                    leading: Stack(
                      children: [
                        CircleAvatar(
                          radius: 28,
                          backgroundColor: role == 'teacher' ? Colors.orange.withOpacity(0.1) : Color(0xFF6C63FF).withOpacity(0.1),
                          backgroundImage: photoUrl != null ? NetworkImage(photoUrl) : null,
                          child: photoUrl == null 
                            ? Icon(role == 'teacher' ? Icons.school : Icons.person, color: role == 'teacher' ? Colors.orange : Color(0xFF6C63FF)) 
                            : null,
                        ),
                        Positioned(
                          bottom: 2, right: 2,
                          child: Container(
                            width: 12, height: 12,
                            decoration: BoxDecoration(
                              color: isOnline ? Colors.green : Colors.grey,
                              shape: BoxShape.circle,
                              border: Border.all(color: cardColor, width: 2)
                            ),
                          ),
                        )
                      ],
                    ),
                    
                    // الاسم + الشارة
                    title: Row(
                      children: [
                        Flexible(child: Text(name, style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16), overflow: TextOverflow.ellipsis)),
                        if (role == 'teacher') ...[
                          SizedBox(width: 5),
                          Icon(Icons.verified, size: 16, color: Colors.blue)
                        ]
                      ],
                    ),
                    
                    // التفاصيل (المستوى + النقاط)
                    subtitle: Padding(
                      padding: const EdgeInsets.only(top: 6.0),
                      child: Row(
                        children: [
                          Container(
                            padding: EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                            decoration: BoxDecoration(
                              color: role == 'teacher' ? Colors.orange[50] : Color(0xFF6C63FF).withOpacity(0.1),
                              borderRadius: BorderRadius.circular(10)
                            ),
                            child: Text(
                              role == 'teacher' ? "معلم" : _getUserTitle(points),
                              style: TextStyle(
                                fontSize: 10, 
                                color: role == 'teacher' ? Colors.orange[800] : Color(0xFF6C63FF),
                                fontWeight: FontWeight.bold
                              ),
                            ),
                          ),
                          if (role == 'student') ...[
                            SizedBox(width: 10),
                            Icon(Icons.star_rounded, size: 14, color: Colors.amber),
                            Text(" $points XP", style: TextStyle(fontSize: 11, color: Colors.grey)),
                          ]
                        ],
                      ),
                    ),
                    
                    // زر المحادثة
                    trailing: InkWell(
                      onTap: () {
                        Navigator.push(context, MaterialPageRoute(
                          builder: (_) => PrivateChatScreen(
                            targetUserIds: user.id,
                            targetUserName: name,
                            targetUserImage: photoUrl,
                          )
                        ));
                      },
                      borderRadius: BorderRadius.circular(50),
                      child: Container(
                        padding: EdgeInsets.all(10),
                        decoration: BoxDecoration(
                          color: isDark ? Colors.white10 : Colors.grey[100],
                          shape: BoxShape.circle
                        ),
                        child: Icon(Icons.chat_bubble_outline_rounded, color: Color(0xFF6C63FF), size: 22),
                      ),
                    ),
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}