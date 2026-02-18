import 'package:flutter/material.dart';
import 'pages/login_page.dart';
import 'pages/dashboard_page.dart';
import 'pages/api_test_page.dart';
import 'pages/student_search_page.dart';

void main() {
  runApp(const AdvisorAIApp());
}

/// Root application widget
/// MaterialApp provides theming, navigation, and app-level configuration
class AdvisorAIApp extends StatelessWidget {
  const AdvisorAIApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'AdvisorAI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        // Custom theme for AdvisorAI
        primarySwatch: Colors.indigo,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1a237e),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        appBarTheme: const AppBarTheme(centerTitle: true, elevation: 0),
        cardTheme: CardThemeData(
          elevation: 2,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
          filled: true,
          fillColor: Colors.grey[50],
        ),
      ),
      // Initial route is the login page
      initialRoute: '/',
      // Route definitions for navigation
      routes: {
        '/': (context) => LoginPage(),
        '/dashboard': (context) => DashboardPage(),
        '/api-test': (context) => ApiTestPage(),
        '/student-search': (context) => StudentSearchPage(),
      },
    );
  }
}
