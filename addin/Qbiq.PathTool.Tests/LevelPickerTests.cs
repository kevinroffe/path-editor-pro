using Qbiq.PathTool.Core;
using Xunit;

namespace Qbiq.PathTool.Tests
{
    public class LevelPickerTests
    {
        static readonly string[] Levels = { "Level 1", "Level 2", "Roof" };

        [Fact] public void The_active_views_level_wins() => Assert.Equal("Level 2", LevelPicker.Choose("Level 2", Levels));
        [Fact] public void No_active_level_falls_back_to_the_lowest() => Assert.Equal("Level 1", LevelPicker.Choose(null, Levels));
        [Fact] public void An_unknown_active_level_falls_back_to_the_lowest() => Assert.Equal("Level 1", LevelPicker.Choose("Site", Levels));
        [Fact] public void A_model_without_levels_gives_null() => Assert.Null(LevelPicker.Choose("Level 1", new string[0]));
    }
}
