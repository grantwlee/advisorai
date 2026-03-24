import 'package:flutter/material.dart';

import 'student_workspace_page.dart';

class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context) {
    final studentId = ModalRoute.of(context)?.settings.arguments as String?;
    if (studentId == null || studentId.isEmpty) {
      return Scaffold(
        appBar: AppBar(title: const Text('Dashboard')),
        body: const Center(
          child: Text('No student selected. Log in with a student ID first.'),
        ),
      );
    }

    return StudentWorkspacePage(
      studentId: studentId,
      pageTitle: 'Student Dashboard',
      showBackButton: false,
    );
  }
}
