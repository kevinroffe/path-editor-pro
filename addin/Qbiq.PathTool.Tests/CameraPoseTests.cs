using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class CameraPoseTests
    {
        const double Eye = 5.15;                       // 1.57 m in feet, roughly

        static void Near(double[] want, double[] got)
        {
            for (var i = 0; i < 3; i++) Assert.Equal(want[i], got[i], 9);
        }

        [Fact]
        public void The_eye_is_at_the_point_with_the_plan_y_flipped_and_the_level_height_plus_eye_height()
        {
            var p = CameraPose.FromPage(10, -20, 0, 13, Eye);
            Near(new[] { 10, 20, 13 + Eye }, p.Eye);
        }

        [Fact]
        public void Yaw_zero_looks_along_plus_x()
        {
            Near(new double[] { 1, 0, 0 }, CameraPose.FromPage(0, 0, 0, 0, Eye).Forward);
        }

        [Fact]
        public void Yaw_ninety_in_the_plan_looks_toward_minus_model_y()
        {
            // plan y runs down the screen and is the negated Revit y, so "90 degrees" in the plan is -y in Revit
            Near(new double[] { 0, -1, 0 }, CameraPose.FromPage(0, 0, 90, 0, Eye).Forward);
        }

        [Fact]
        public void Yaw_one_eighty_and_minus_ninety()
        {
            Near(new double[] { -1, 0, 0 }, CameraPose.FromPage(0, 0, 180, 0, Eye).Forward);
            Near(new double[] { 0, 1, 0 }, CameraPose.FromPage(0, 0, -90, 0, Eye).Forward);
        }

        [Fact]
        public void The_view_stays_level_and_the_up_direction_is_z()
        {
            var p = CameraPose.FromPage(3, -4, 37, 0, Eye);
            Near(new double[] { 0, 0, 1 }, p.Up);
            Assert.Equal(0.0, p.Forward[2]);
            Assert.Equal(1.0, p.Forward[0] * p.Forward[0] + p.Forward[1] * p.Forward[1], 9);     // a unit direction
        }

        [Fact]
        public void A_huge_yaw_still_gives_a_unit_direction()
        {
            var p = CameraPose.FromPage(0, 0, 7200 + 45, 0, Eye);
            Assert.Equal(1.0, p.Forward[0] * p.Forward[0] + p.Forward[1] * p.Forward[1], 9);
        }
    }

    public class CameraMessageTests
    {
        [Fact]
        public void A_camera_message_carries_the_position_yaw_and_level_height()
        {
            Assert.True(CameraMessage.TryParse("{\"type\":\"camera\",\"x\":10.5,\"y\":-20,\"yaw\":45,\"elevation\":13}", out var m));
            Assert.Equal("camera", m.Type);
            Assert.Equal((10.5, -20.0, 45.0, 13.0), (m.X, m.Y, m.Yaw, m.Elevation));
        }

        [Fact]
        public void Start_and_stop_need_nothing_else()
        {
            Assert.True(CameraMessage.TryParse("{\"type\":\"cameraStart\"}", out var a) && a.Type == "cameraStart");
            Assert.True(CameraMessage.TryParse("{\"type\":\"cameraStop\"}", out var b) && b.Type == "cameraStop");
        }

        [Fact]
        public void A_camera_message_without_a_position_is_rejected()
        {
            Assert.False(CameraMessage.TryParse("{\"type\":\"camera\",\"yaw\":45}", out _));
            Assert.False(CameraMessage.TryParse("{\"type\":\"camera\",\"x\":\"far\",\"y\":1,\"yaw\":0}", out _));
        }

        [Fact]
        public void Other_messages_and_bad_json_are_not_camera_messages()
        {
            Assert.False(CameraMessage.TryParse("{\"type\":\"readModel\"}", out _));
            Assert.False(CameraMessage.TryParse("not json", out _));
            Assert.False(CameraMessage.TryParse("{\"x\":1}", out _));
        }

        [Fact]
        public void Not_a_number_is_rejected()
        {
            Assert.False(CameraMessage.TryParse("{\"type\":\"camera\",\"x\":1e999,\"y\":1,\"yaw\":0,\"elevation\":0}", out _));
        }
    }
}
